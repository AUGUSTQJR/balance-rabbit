import Cocoa

final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class BubblePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {

    private var petPanel: NSPanel!
    private var petView: PetView!
    private var bubblePanel: NSPanel!
    private var bubbleView: BubbleView!
    private var statusItem: NSStatusItem!

    private let api = APIClient()
    private var stats: Stats?
    private var isLoading = false
    private var refreshTimer: Timer?
    private var hideTask: DispatchWorkItem?
    private var lastLowNotifyAt: Date?

    // 边缘吸附（趴边小图标）
    private var dockEdge: Edge?
    private var dockAnchor: CGFloat = 0
    private var dockHoverExpanded = false
    private var dockDragStartOrigin: NSPoint = .zero
    private var dockPanel: NSPanel!
    private var dockView: DockView!
    /// 吸附时兔子所在的屏幕（混合 DPI/多屏时不要用 petPanel.screen）
    private var dockScreen: NSScreen?
    private var startupChecked = false
    /// 气泡临时挂靠的宿主窗口（兔子或边缘图标）
    private weak var bubbleHostWindow: NSWindow?
    /// 逻辑上气泡是否展开（窗口常驻、只用 alpha 控制显隐）
    private var bubbleVisible = false

    // MARK: - 生命周期

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildPetWindow()
        buildBubbleWindow()
        buildDockWindow()
        buildStatusItem()
        scheduleTimer()
        NSWorkspace.shared.notificationCenter.addObserver(self,
                                                          selector: #selector(handleWake),
                                                          name: NSWorkspace.didWakeNotification,
                                                          object: nil)
        DistributedNotificationCenter.default().addObserver(self,
                                                            selector: #selector(handleExternalShow),
                                                            name: NSNotification.Name("top.rabbitj.balancepet.show"),
                                                            object: nil)
        NotificationCenter.default.addObserver(self,
                                               selector: #selector(handleScreenChange),
                                               name: NSApplication.didChangeScreenParametersNotification,
                                               object: nil)
        refresh(showBubble: false)

        if !Settings.shared.didWelcome {
            Settings.shared.didWelcome = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                self?.showBubblePanel()
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            self?.runStartupAccountCheck()
            self?.showStorageWarningIfNeeded()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        refreshTimer?.invalidate()
    }

    // MARK: - 窗口搭建

    private func buildPetWindow() {
        let side = CGFloat(Settings.shared.petSize)
        let size = NSSize(width: side, height: side)
        let panel = PetPanel(contentRect: NSRect(origin: .zero, size: size),
                             styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered,
                             defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = false
        panel.appearance = NSAppearance(named: .aqua)

        let view = PetView(frame: NSRect(origin: .zero, size: size))
        view.autoresizingMask = [.width, .height]
        panel.contentView = view
        panel.setFrameOrigin(initialPetOrigin(size: size))

        petView = view
        petPanel = panel

        view.onActivate = { [weak self] in self?.petClicked() }
        view.onMoved = { [weak self] origin in
            Settings.shared.petX = Double(origin.x)
            Settings.shared.petY = Double(origin.y)
            self?.hideBubble(animated: false)
        }
        view.onResizeBy = { [weak self] delta in
            guard let self = self else { return }
            self.applyPetSize(self.currentPetSize + (delta > 0 ? 8 : -8))
        }
        view.onDragEnded = { [weak self] in self?.handleDragEnded() }
        view.onContextMenu = { [weak self] event in
            guard let self = self else { return }
            let menu = NSMenu()
            self.populate(menu)
            NSMenu.popUpContextMenu(menu, with: event, for: self.petView)
        }

        if Settings.shared.petHidden {
            panel.orderOut(nil)
        } else {
            panel.orderFrontRegardless()
        }
    }

    private func buildBubbleWindow() {
        let size = BubbleView.size
        let panel = BubblePanel(contentRect: NSRect(origin: .zero, size: size),
                                styleMask: [.borderless, .nonactivatingPanel],
                                backing: .buffered,
                                defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.ignoresMouseEvents = false
        panel.acceptsMouseMovedEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.appearance = NSAppearance(named: .aqua)

        let view = BubbleView(frame: NSRect(origin: .zero, size: size))
        view.autoresizingMask = [.width, .height]
        panel.contentView = view
        panel.alphaValue = 0

        view.onRefresh = { [weak self] in self?.refresh(showBubble: true) }
        view.onClose = { [weak self] in self?.hideBubble(animated: true) }
        view.onInteraction = { [weak self] in self?.scheduleHide(after: 15) }

        bubbleView = view
        bubblePanel = panel

        // 关键：气泡窗口「常驻但不显示」（alpha 0 + 忽略鼠标）。
        // 窗口如果在全屏 App 期间才第一次 orderFront，macOS 会把它放到桌面 Space，
        // 表现就是「全屏下点兔子看不到气泡」；先让它进过场，之后与兔子一样出现在所有 Space。
        panel.ignoresMouseEvents = true
        panel.orderFrontRegardless()
    }

    private func buildDockWindow() {
        let size = DockView.size(for: .left)
        let panel = PetPanel(contentRect: NSRect(origin: .zero, size: size),
                             styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered,
                             defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.appearance = NSAppearance(named: .aqua)
        panel.alphaValue = 0

        let view = DockView(frame: NSRect(origin: .zero, size: size))
        view.autoresizingMask = [.width, .height]
        panel.contentView = view

        view.onActivate = { [weak self] in self?.undock(animated: true) }
        view.onHoverChanged = { [weak self] hovering in self?.handleDockHover(hovering) }
        view.onDragBegan = { [weak self] in self?.beginDockDrag() }
        view.onDragMove = { [weak self] delta in self?.moveDockIcon(delta: delta) }
        view.onContextMenu = { [weak self] event in
            guard let self = self else { return }
            let menu = NSMenu()
            self.populate(menu)
            NSMenu.popUpContextMenu(menu, with: event, for: self.dockView)
        }

        dockPanel = panel
        dockView = view
    }

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "hare.fill", accessibilityDescription: "余额兔")
            button.imagePosition = .imageLeft
            button.image?.isTemplate = true
        }
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        updateStatusTitle()
    }

    private func initialPetOrigin(size: NSSize) -> NSPoint {
        if let x = Settings.shared.petX, let y = Settings.shared.petY {
            let point = NSPoint(x: x, y: y)
            let visible = NSScreen.screens.contains { $0.visibleFrame.intersects(NSRect(origin: point, size: size)) }
            if visible { return point }
        }
        let screen = NSScreen.main ?? NSScreen.screens.first
        let frame = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        return NSPoint(x: frame.maxX - size.width - 36, y: frame.minY + 24)
    }

    // MARK: - 查询

    private func refresh(showBubble show: Bool = false) {
        guard !isLoading else { return }
        isLoading = true
        bubbleView.isLoading = true
        if show { showBubblePanel() }

        Task { @MainActor in
            do {
                let result = try await api.loadStats()
                self.isLoading = false
                self.petView.lowBalance = result.isLow && Settings.shared.lowThreshold > 0
                self.stats = result
                self.bubbleView.isLoading = false
                self.bubbleView.hoverDay = nil
                self.bubbleView.selectedDay = nil
                self.bubbleView.stats = result
                self.updateStatusTitle()
                if self.bubbleVisible {
                    self.layoutBubble()
                    self.bubbleView.needsDisplay = true
                }
                self.checkLowBalance(result)
            } catch {
                self.isLoading = false
                self.bubbleView.isLoading = false
                var failed = self.stats ?? Stats()
                failed.error = (error as? LocalizedError)?.errorDescription ?? "\(error)"
                self.stats = failed
                self.bubbleView.stats = failed
                self.updateStatusTitle()
                if self.bubbleVisible {
                    self.layoutBubble()
                    self.bubbleView.needsDisplay = true
                }
            }
        }
    }

    private func checkLowBalance(_ value: Stats) {
        guard let balance = value.balance else { return }
        let threshold = Settings.shared.lowThreshold
        guard threshold > 0, balance < threshold else { return }
        if let last = lastLowNotifyAt, Date().timeIntervalSince(last) < 6 * 3600 { return }
        lastLowNotifyAt = Date()

        let body = "余额 \(money2(balance)) 已低于 ¥\(Int(threshold))，记得充值～"
        let script = "display notification \"\(body)\" with title \"余额兔提醒\""
        DispatchQueue.global(qos: .utility).async {
            _ = run("/usr/bin/osascript", ["-e", script])
        }
    }

    private func updateStatusTitle() {
        guard let button = statusItem?.button else { return }
        let balance = stats?.balance
        let title = balance.map { String(format: " %.2f", $0) } ?? " —"
        let low = (balance ?? .greatestFiniteMagnitude) < Settings.shared.lowThreshold
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .medium),
            .foregroundColor: low ? NSColor.systemRed : NSColor.labelColor
        ]
        button.attributedTitle = NSAttributedString(string: "¥" + title, attributes: attributes)
    }

    // MARK: - 气泡

    private func petClicked() {
        guard !Settings.shared.petHidden else { return }
        if dockEdge != nil {
            undock(animated: true)
            return
        }
        if bubbleVisible {
            hideBubble(animated: true)
        } else {
            showBubblePanel()
        }
        let stale = stats.map { Date().timeIntervalSince($0.updatedAt) > 30 } ?? true
        if stale && !isLoading {
            refresh(showBubble: false)
        }
    }

    private func showBubblePanel() {
        hideTask?.cancel()
        bubbleView.stats = stats
        bubbleView.isLoading = isLoading
        bubbleView.hoverDay = nil
        bubbleView.selectedDay = nil
        bubbleView.tailX = 150
        layoutBubble()
        attachBubbleToHost()
        bubbleVisible = true
        bubblePanel.ignoresMouseEvents = false
        bubblePanel.alphaValue = 0
        bubblePanel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.16
            bubblePanel.animator().alphaValue = 1
        }
        scheduleHide(after: 15)
    }

    private func layoutBubble() {
        let hostScreen = dockEdge != nil ? dockScreen : petPanel.screen
        guard let screen = hostScreen ?? NSScreen.main ?? NSScreen.screens.first else { return }
        let size = BubbleView.size
        let petFrame = (dockEdge != nil && dockPanel.isVisible) ? dockPanel.frame : petPanel.frame
        let visible = screen.visibleFrame

        var x = petFrame.midX - size.width / 2
        var y = petFrame.maxY + 4
        var tailUp = false
        if y + size.height > visible.maxY {
            y = petFrame.minY - size.height - 4
            tailUp = true
        }
        x = min(max(visible.minX + 4, x), visible.maxX - size.width - 4)
        y = min(max(visible.minY + 4, y), visible.maxY - size.height - 4)

        bubbleView.tailUp = tailUp
        bubbleView.tailX = min(max(petFrame.midX - x, 26), size.width - 26)
        bubblePanel.setFrame(NSRect(origin: NSPoint(x: x, y: y), size: size), display: true)
    }

    private func scheduleHide(after seconds: TimeInterval) {
        hideTask?.cancel()
        let task = DispatchWorkItem { [weak self] in self?.hideBubble(animated: true) }
        hideTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: task)
    }

    private func hideBubble(animated: Bool) {
        hideTask?.cancel()
        bubbleView.hoverDay = nil
        bubbleView.selectedDay = nil
        guard bubbleVisible else {
            detachBubbleFromHost()
            return
        }
        bubbleVisible = false
        bubblePanel.ignoresMouseEvents = true
        let finish = { [weak self] in
            guard let self = self else { return }
            self.bubblePanel.alphaValue = 0
            self.detachBubbleFromHost()
        }
        if animated {
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = 0.15
                bubblePanel.animator().alphaValue = 0
            }, completionHandler: finish)
        } else {
            finish()
        }
    }

    /// 把气泡挂成兔子（或边缘图标）的子窗口：
    /// 子窗口一定和父窗口在同一个 Space，这样全屏 App 所在 Space 里也能看见气泡。
    /// 不挂靠时，气泡第一次在全屏 Space 里 orderFront 会被系统放到桌面 Space，表现为「全屏下看不到」。
    private func attachBubbleToHost() {
        let host: NSWindow = (dockEdge != nil && dockPanel.isVisible) ? dockPanel : petPanel
        if bubbleHostWindow !== host {
            detachBubbleFromHost()
            host.addChildWindow(bubblePanel, ordered: .above)
            bubbleHostWindow = host
        }
    }

    private func detachBubbleFromHost() {
        guard bubbleHostWindow != nil else { return }
        bubbleHostWindow?.removeChildWindow(bubblePanel)
        bubbleHostWindow = nil
    }

    // MARK: - 定时器

    private func scheduleTimer() {
        refreshTimer?.invalidate()
        let minutes = Settings.shared.refreshMinutes
        guard minutes > 0 else { return }
        let timer = Timer(timeInterval: TimeInterval(minutes * 60),
                          target: self,
                          selector: #selector(timerFired),
                          userInfo: nil,
                          repeats: true)
        timer.tolerance = 10
        RunLoop.main.add(timer, forMode: .common)
        refreshTimer = timer
    }

    @objc private func timerFired() {
        refresh(showBubble: false)
    }

    @objc private func handleExternalShow() {
        if Settings.shared.petHidden {
            Settings.shared.petHidden = false
        }
        if dockEdge != nil {
            undock(animated: true)
        }
        petPanel.alphaValue = 1
        petPanel.orderFrontRegardless()
        petView.needsDisplay = true
        showBubblePanel()
        refresh(showBubble: false)
    }

    @objc private func handleWake() {
        refresh(showBubble: false)
    }




    // MARK: - 边缘吸附（左/右边缘电子指示器）

    private let dockThreshold: CGFloat = 28

    private func dockTargetEdge() -> Edge? {
        guard Settings.shared.edgeDockEnabled, !Settings.shared.petHidden else { return nil }
        guard let screen = petPanel.screen ?? NSScreen.main else { return nil }
        let visible = screen.visibleFrame
        let frame = petPanel.frame
        // 只支持左 / 右
        let candidates: [(Edge, CGFloat)] = [
            (.left, frame.minX - visible.minX),
            (.right, visible.maxX - frame.maxX)
        ]
        guard let best = candidates.min(by: { $0.1 < $1.1 }), best.1 <= dockThreshold else { return nil }
        return best.0
    }

    private func clampDockAnchor(_ anchor: CGFloat, edge: Edge, screen: NSScreen) -> CGFloat {
        let visible = screen.visibleFrame
        let size = DockView.size(for: edge)
        let low = visible.minY + size.height / 2
        let high = visible.maxY - size.height / 2
        return high < low ? low : min(max(low, anchor), high)
    }

    private func dockWindowFrame(edge: Edge, expanded: Bool) -> NSRect {
        let screen = dockScreen ?? petPanel.screen ?? NSScreen.main ?? NSScreen.screens[0]
        let visible = screen.visibleFrame
        let size = DockView.size(for: edge)
        let hidden = DockView.hiddenThickness(for: edge)
        let peek: CGFloat = expanded ? 14 : 0
        let lowY = visible.minY
        let highY = visible.maxY - size.height
        let y = highY < lowY ? lowY : min(max(lowY, dockAnchor - size.height / 2), highY)
        switch edge {
        case .left:
            return NSRect(x: visible.minX - hidden + peek, y: y, width: size.width, height: size.height)
        case .right:
            return NSRect(x: visible.maxX - size.width + hidden - peek, y: y, width: size.width, height: size.height)
        default:
            return NSRect(x: visible.minX - hidden + peek, y: y, width: size.width, height: size.height)
        }
    }

    private func popOutOrigin(edge: Edge, anchor: CGFloat) -> NSPoint {
        guard let screen = dockScreen ?? petPanel.screen ?? NSScreen.main else { return petPanel.frame.origin }
        let visible = screen.visibleFrame
        let size = petPanel.frame.size
        func clampX(_ value: CGFloat) -> CGFloat {
            let low = visible.minX + 6
            let high = visible.maxX - size.width - 6
            return high < low ? low : min(max(low, value), high)
        }
        func clampY(_ value: CGFloat) -> CGFloat {
            let low = visible.minY + 6
            let high = visible.maxY - size.height - 6
            return high < low ? low : min(max(low, value), high)
        }
        _ = clampX
        switch edge {
        case .left:
            return NSPoint(x: visible.minX + 8, y: clampY(anchor - size.height / 2))
        case .right:
            return NSPoint(x: visible.maxX - size.width - 8, y: clampY(anchor - size.height / 2))
        default:
            return NSPoint(x: visible.minX + 8, y: clampY(anchor - size.height / 2))
        }
    }

    private func beginDockDrag() {
        dockDragStartOrigin = dockPanel.frame.origin
    }

    private func moveDockIcon(delta: NSPoint) {
        guard let edge = dockEdge, let screen = dockScreen ?? petPanel.screen ?? NSScreen.main else { return }
        let visible = screen.visibleFrame
        let size = DockView.size(for: edge)
        let hidden = DockView.hiddenThickness(for: edge)
        var origin = dockDragStartOrigin
        origin.y += delta.y
        origin.y = min(max(visible.minY, origin.y), max(visible.minY, visible.maxY - size.height))
        dockAnchor = origin.y + size.height / 2
        _ = hidden
        dockHoverExpanded = false
        dockPanel.setFrameOrigin(origin)
        if bubbleVisible { layoutBubble() }
    }

    private func dock(to edge: Edge) {
        guard let screen = petPanel.screen ?? NSScreen.main else { return }
        dockScreen = screen
        dockEdge = edge
        dockHoverExpanded = false
        hideBubble(animated: false)
        let anchor = petPanel.frame.midY
        dockAnchor = clampDockAnchor(anchor, edge: edge, screen: screen)

        let size = DockView.size(for: edge)
        dockView.edge = edge
        dockView.frame = NSRect(origin: .zero, size: size)
        dockView.needsDisplay = true
        dockPanel.ignoresMouseEvents = false
        dockPanel.setFrame(dockWindowFrame(edge: edge, expanded: false), display: true)
        dockPanel.alphaValue = 0
        dockPanel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.15
            dockPanel.animator().alphaValue = 1
        }
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.10
            petPanel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            guard let self = self else { return }
            if self.dockEdge != nil {
                self.petPanel.orderOut(nil)
            }
            self.petPanel.alphaValue = 1
        })
    }

    private func hideDockIcon(animated: Bool) {
        guard dockPanel.isVisible else { return }
        if animated {
            NSAnimationContext.runAnimationGroup({ context in
                context.duration = 0.12
                dockPanel.animator().alphaValue = 0
            }, completionHandler: { [weak self] in
                guard let self = self else { return }
                if self.dockEdge == nil {
                    self.dockPanel.orderOut(nil)
                    self.dockPanel.alphaValue = 1
                }
            })
        } else {
            dockPanel.orderOut(nil)
            dockPanel.alphaValue = 1
        }
    }

    private func undock(animated: Bool = true) {
        guard let edge = dockEdge else { return }
        let anchor = dockAnchor
        let origin = popOutOrigin(edge: edge, anchor: anchor)
        dockScreen = nil
        dockEdge = nil
        dockHoverExpanded = false
        hideDockIcon(animated: animated)
        petPanel.alphaValue = 0
        petPanel.setFrameOrigin(origin)
        petPanel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            petPanel.animator().alphaValue = 1
        }
        savePetPosition()
        petView.needsDisplay = true
        if bubbleVisible { layoutBubble() }
    }

    private func handleDockHover(_ hovering: Bool) {
        guard let edge = dockEdge else { return }
        guard hovering != dockHoverExpanded else { return }
        dockHoverExpanded = hovering
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.14
            dockPanel.animator().setFrame(dockWindowFrame(edge: edge, expanded: hovering), display: true)
        }
    }

    private func handleDragEnded() {
        if let edge = dockTargetEdge() {
            dock(to: edge)
        } else {
            clampPetOnScreen()
            savePetPosition()
        }
    }

    private func savePetPosition() {
        Settings.shared.petX = Double(petPanel.frame.origin.x)
        Settings.shared.petY = Double(petPanel.frame.origin.y)
    }

    // MARK: - 兔子大小

    private var currentPetSize: CGFloat {
        petPanel?.frame.width ?? CGFloat(Settings.shared.petSize)
    }

    private func clampSize(_ value: CGFloat) -> CGFloat {
        let screen = petPanel?.screen ?? NSScreen.main
        let maxSide = min(320, (screen?.visibleFrame.height ?? 900) - 40)
        return min(max(value, 96), maxSide)
    }

    private func clampPetOnScreen() {
        guard let screen = petPanel.screen ?? NSScreen.main else { return }
        let visible = screen.visibleFrame
        var origin = petPanel.frame.origin
        origin.x = min(max(visible.minX, origin.x), visible.maxX - petPanel.frame.width)
        origin.y = min(max(visible.minY, origin.y), visible.maxY - petPanel.frame.height)
        if origin != petPanel.frame.origin {
            petPanel.setFrameOrigin(origin)
        }
    }

    /// 以「底部中心」为锚点缩放，兔子变大时向上长
    private func applyPetSize(_ requested: CGFloat) {
        guard petPanel != nil else { return }
        let side = clampSize(requested)
        let frame = petPanel.frame
        let origin = NSPoint(x: frame.midX - side / 2, y: frame.minY)
        petPanel.setFrame(NSRect(origin: origin, size: NSSize(width: side, height: side)), display: true)
        clampPetOnScreen()
        Settings.shared.petSize = Double(side)
        if dockEdge == nil {
            savePetPosition()
        }
        petView.needsDisplay = true
        if bubbleVisible {
            layoutBubble()
        }
    }

    // MARK: - 菜单

    private func makeItem(_ title: String, _ action: Selector?, _ key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    private func populate(_ menu: NSMenu) {
        menu.removeAllItems()

        let balance = stats?.balance
        let header = balance.map { "余额 \(money2($0))" } ?? "余额 —"
        let headerItem = NSMenuItem(title: header, action: nil, keyEquivalent: "")
        headerItem.isEnabled = false
        menu.addItem(headerItem)

        if let error = stats?.error {
            let item = NSMenuItem(title: "⚠︎ \(error)", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        if let userId = stats?.accountUserId {
            let item = NSMenuItem(title: "账户 #\(userId)", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        if stats?.multipleAccounts == true {
            let item = NSMenuItem(title: "⚠︎ 当前 Key 可见多个账户，已按账户过滤",
                                  action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        if let hint = Credentials.keyHint() {
            let item = NSMenuItem(title: "当前 Key 尾号 \(hint)", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        if let stats = stats, stats.weekRecharged > 0 {
            let item = NSMenuItem(title: "近 7 天充值 \(money2(stats.weekRecharged))",
                                  action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }
        if stats?.accountInactive == true {
            let item = NSMenuItem(title: "接口状态：is_active = false（如能正常使用可忽略）",
                                  action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }

        menu.addItem(.separator())
        menu.addItem(makeItem("刷新余额", #selector(menuRefresh), "r"))
        menu.addItem(makeItem("复制余额", #selector(menuCopyBalance)))
        menu.addItem(.separator())
        menu.addItem(makeItem("打开商店 / 充值", #selector(menuOpenStore)))
        menu.addItem(.separator())

        // 自动刷新
        let refreshMenu = NSMenu()
        for minutes in [0, 5, 10, 30, 60] {
            let item = makeItem(minutes == 0 ? "关闭定时刷新" : "每 \(minutes) 分钟", #selector(menuSetRefresh(_:)))
            item.tag = minutes
            item.state = Settings.shared.refreshMinutes == minutes ? .on : .off
            refreshMenu.addItem(item)
        }
        let refreshParent = NSMenuItem(title: "自动刷新", action: nil, keyEquivalent: "")
        refreshParent.submenu = refreshMenu
        menu.addItem(refreshParent)

        // 低余额提醒阈值
        let thresholdMenu = NSMenu()
        for threshold in [0.0, 10.0, 20.0, 50.0, 100.0] {
            let item = makeItem(threshold == 0 ? "关闭提醒" : "低于 ¥\(Int(threshold)) 时提醒", #selector(menuSetThreshold(_:)))
            item.tag = Int(threshold)
            item.state = abs(Settings.shared.lowThreshold - threshold) < 0.01 ? .on : .off
            thresholdMenu.addItem(item)
        }
        let thresholdParent = NSMenuItem(title: "低余额提醒", action: nil, keyEquivalent: "")
        thresholdParent.submenu = thresholdMenu
        menu.addItem(thresholdParent)

        // 开机自启
        let loginItem = makeItem("开机自动启动", #selector(menuToggleLoginItem))
        loginItem.state = LoginItem.isEnabled() ? .on : .off
        menu.addItem(loginItem)

        menu.addItem(.separator())

        let sizeMenu = NSMenu()
        let presets: [(String, CGFloat)] = [("小 · 120", 120), ("中 · 176", 176), ("大 · 240", 240), ("特大 · 300", 300)]
        for (title, value) in presets {
            let item = makeItem(title, #selector(menuSetSize(_:)))
            item.tag = Int(value)
            item.state = abs(currentPetSize - value) < 2 ? .on : .off
            sizeMenu.addItem(item)
        }
        sizeMenu.addItem(.separator())
        sizeMenu.addItem(makeItem("放大", #selector(menuBigger)))
        sizeMenu.addItem(makeItem("缩小", #selector(menuSmaller)))
        let sizeHint = NSMenuItem(title: "⌥ / ⌘ + 滚轮可自由缩放", action: nil, keyEquivalent: "")
        sizeHint.isEnabled = false
        sizeMenu.addItem(sizeHint)
        let sizeParent = NSMenuItem(title: "兔子大小", action: nil, keyEquivalent: "")
        sizeParent.submenu = sizeMenu
        menu.addItem(sizeParent)

        if dockEdge != nil {
            menu.addItem(makeItem("从边缘弹出", #selector(menuUndock)))
        }
        let dockItem = makeItem("拖到屏幕边缘自动吸附", #selector(menuToggleDock))
        dockItem.state = Settings.shared.edgeDockEnabled ? .on : .off
        menu.addItem(dockItem)

        let hideItem = makeItem(Settings.shared.petHidden ? "显示兔子" : "隐藏兔子", #selector(menuTogglePet))
        menu.addItem(hideItem)
        menu.addItem(makeItem("把兔子放回屏幕右下角", #selector(menuResetPetPosition)))

        let installItem = makeItem("安装到「应用程序」文件夹…", #selector(menuInstallToApplications))
        installItem.isEnabled = !installPath.hasPrefix(Bundle.main.bundlePath)
        menu.addItem(installItem)

        menu.addItem(.separator())
        let keyTitle = Credentials.hasKey ? "更换 API Key（换账号）…" : "设置 API Key…"
        menu.addItem(makeItem(keyTitle, #selector(menuSetAPIKey)))
        menu.addItem(makeItem("关于账号与 API Key…", #selector(menuKeyInfo)))
        menu.addItem(.separator())
        let versionItem = NSMenuItem(title: "余额兔 v\(appVersion())", action: nil, keyEquivalent: "")
        versionItem.isEnabled = false
        menu.addItem(versionItem)
        menu.addItem(makeItem("退出余额兔", #selector(menuQuit), "q"))
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        populate(menu)
    }

    func menuWillOpen(_ menu: NSMenu) {
        guard menu == statusItem?.menu else { return }
        if let event = NSApp.currentEvent, event.clickCount >= 2 {
            menu.cancelTracking()
            DispatchQueue.main.async { [weak self] in
                self?.showPetOnCurrentScreen()
            }
        }
    }

    // MARK: - 菜单动作

    @objc private func menuRefresh() {
        refresh(showBubble: true)
    }

    @objc private func menuCopyBalance() {
        let text = stats?.balance.map { money2($0) } ?? "—"
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        showBubblePanel()
    }

    @objc private func menuOpenStore() {
        if let url = URL(string: "https://www.rabbitj.top/shop") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func menuToggleDock() {
        Settings.shared.edgeDockEnabled.toggle()
        if !Settings.shared.edgeDockEnabled {
            undock(animated: true)
        }
    }

    @objc private func menuUndock() {
        undock(animated: true)
    }

    @objc private func menuSetSize(_ sender: NSMenuItem) {
        applyPetSize(CGFloat(sender.tag))
        showBubblePanel()
    }

    @objc private func menuBigger() {
        applyPetSize(currentPetSize + 12)
        showBubblePanel()
    }

    @objc private func menuSmaller() {
        applyPetSize(currentPetSize - 12)
        showBubblePanel()
    }

    @objc private func menuSetRefresh(_ sender: NSMenuItem) {
        Settings.shared.refreshMinutes = sender.tag
        scheduleTimer()
        refresh(showBubble: true)
    }

    @objc private func menuSetThreshold(_ sender: NSMenuItem) {
        Settings.shared.lowThreshold = Double(sender.tag)
        if let value = stats {
            petView.lowBalance = value.isLow && Settings.shared.lowThreshold > 0
            bubbleView.stats = value
        }
        showBubblePanel()
    }

    @objc private func menuToggleLoginItem() {
        if LoginItem.isEnabled() {
            LoginItem.disable()
        } else if let error = LoginItem.enable() {
            alert(title: "开启开机自启失败", message: error)
        }
    }

    @objc private func menuTogglePet() {
        Settings.shared.petHidden.toggle()
        if Settings.shared.petHidden {
            petPanel.orderOut(nil)
            dockPanel.orderOut(nil)
            hideBubble(animated: false)
        } else if let edge = dockEdge {
            dockPanel.setFrame(dockWindowFrame(edge: edge, expanded: false), display: true)
            dockPanel.alphaValue = 1
            dockPanel.orderFrontRegardless()
            showBubblePanel()
        } else {
            petPanel.alphaValue = 1
            petPanel.orderFrontRegardless()
            showBubblePanel()
        }
    }

    @objc private func menuSetAPIKey() {
        showKeyDialog(firstTime: false)
    }

    @objc private func menuKeyInfo() {
        NSApp.activate(ignoringOtherApps: true)
        let hint = Credentials.keyHint() ?? "未设置"
        let account = stats?.accountUserId.map { "#\($0)" } ?? "未知"
        let text = "当前 Key 尾号：\(hint)\n账户：\(account)\n\n" +
            "每个 macOS 用户 / 每台电脑都要填自己的 Key，填了别人的 Key 就会显示别人的余额。\n" +
            "Key 只保存在本机钥匙串里，不会写到任何共享文件。\n" +
            "换账号时用菜单「更换 API Key（换账号）…」。"
        let alert = NSAlert()
        alert.messageText = "关于账号与 API Key"
        alert.informativeText = text
        alert.addButton(withTitle: "好的")
        alert.addButton(withTitle: "打开「钥匙串访问」")
        if alert.runModal() == .alertSecondButtonReturn {
            NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Utilities/Keychain Access.app"))
        }
    }

    @objc private func menuResetPetPosition() {
        resetPetPosition(showBubble: true)
    }

    @objc private func menuQuit() {
        NSApp.terminate(nil)
    }

    // MARK: - 账号（Key 严格按人隔离）

    private func runStartupAccountCheck() {
        guard !startupChecked else { return }
        startupChecked = true
        let version = appVersion()
        let previous = Settings.shared.lastRunVersion
        if !Credentials.hasKey {
            showKeyDialog(firstTime: true)
        } else if previous != version {
            confirmAccount()
        }
        Settings.shared.lastRunVersion = version
    }

    private func confirmAccount() {
        NSApp.activate(ignoringOtherApps: true)
        let hint = Credentials.keyHint() ?? ""
        let text = "检测到本机已保存 API Key（尾号 " + hint + "）。\n\n" +
            "如果这台电脑现在换别人使用，继续用这个 Key 会显示原来账号的余额。\n" +
            "要继续使用这个 Key 吗？"
        let alert = NSAlert()
        alert.messageText = "余额兔 · 确认账号"
        alert.informativeText = text
        alert.addButton(withTitle: "否，重新填写")
        alert.addButton(withTitle: "是，继续使用")
        if alert.runModal() == .alertFirstButtonReturn {
            showKeyDialog(firstTime: false)
        }
    }

    private func showKeyDialog(firstTime: Bool) {
        NSApp.activate(ignoringOtherApps: true)
        var text = "每个 macOS 用户 / 每台电脑都要填自己的 Key。\n" +
            "填了别人的 Key 就会显示别人的余额。\n\n" +
            "Key 以 sk- 开头，可在 rabbitj.top 的账号页复制；只会保存到本机钥匙串。"
        if let hint = Credentials.keyHint() {
            text += "\n\n当前已保存的 Key 尾号：" + hint
        }
        let alert = NSAlert()
        alert.messageText = "填写你自己的 rabbitj.top API Key"
        alert.informativeText = text
        alert.addButton(withTitle: "保存")
        alert.addButton(withTitle: firstTime ? "稍后再说" : "取消")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24))
        field.placeholderString = "sk-..."
        var prefilled = false
        if firstTime, !Credentials.hasKey, let legacy = Credentials.legacySharedKey() {
            field.stringValue = legacy
            prefilled = true
        }
        if prefilled {
            alert.informativeText = text + "\n\n检测到这台电脑以前的共享配置里有 Key，已帮你预填；确认后只会保存到本机钥匙串。"
        }
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let key = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        if let error = Credentials.save(key) {
            self.alert(title: "保存失败", message: error)
            return
        }
        Settings.shared.lastRunVersion = appVersion()
        refresh(showBubble: true)
    }

    // MARK: - 屏幕变化 / 复位

    @objc private func handleScreenChange() {
        if let edge = dockEdge {
            if let screen = dockScreen ?? NSScreen.main {
                dockAnchor = clampDockAnchor(dockAnchor, edge: edge, screen: screen)
                dockPanel.setFrame(dockWindowFrame(edge: edge, expanded: dockHoverExpanded), display: true)
            }
        } else {
            ensurePetVisible()
        }
        if bubbleVisible { layoutBubble() }
    }

    private var storageWarningShown = false

    private func showStorageWarningIfNeeded() {
        guard !AppStorage.writable, !storageWarningShown else { return }
        storageWarningShown = true
        let text = "当前安全策略禁止写入设置目录，API Key 与设置只能本次运行有效。\n" +
            "建议把「余额兔.app」放到「应用程序」或下载目录，或允许它写入 ~/Library/Application Support。"
        alert(title: "无法保存设置", message: text)
    }

    private func ensurePetVisible() {
        guard petPanel != nil else { return }
        let frame = petPanel.frame
        let onScreen = NSScreen.screens.contains { $0.visibleFrame.intersects(frame) }
        if onScreen {
            clampPetOnScreen()
            savePetPosition()
        } else if !Settings.shared.petHidden {
            resetPetPosition(showBubble: false)
        }
    }

    private func resetPetPosition(showBubble: Bool) {
        if dockEdge != nil { undock(animated: false) }
        let screen = screenUnderMouse() ?? NSScreen.main ?? NSScreen.screens.first
        let visible = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let size = petPanel.frame.size
        petPanel.setFrameOrigin(NSPoint(x: visible.maxX - size.width - 36, y: visible.minY + 24))
        savePetPosition()
        petPanel.alphaValue = 1
        if !Settings.shared.petHidden { petPanel.orderFrontRegardless() }
        petView.needsDisplay = true
        if showBubble { showBubblePanel() }
    }

    private func screenUnderMouse() -> NSScreen? {
        let point = NSEvent.mouseLocation
        return NSScreen.screens.first { $0.frame.contains(point) } ?? NSScreen.main
    }

    private func showPetOnCurrentScreen() {
        Settings.shared.petHidden = false
        if dockEdge != nil { undock(animated: false) }
        let screen = screenUnderMouse() ?? NSScreen.main ?? NSScreen.screens.first
        let visible = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let size = petPanel.frame.size
        petPanel.setFrameOrigin(NSPoint(x: visible.midX - size.width / 2, y: visible.minY + 24))
        savePetPosition()
        petPanel.alphaValue = 1
        petPanel.orderFrontRegardless()
        petView.needsDisplay = true
        showBubblePanel()
    }

    // MARK: - 安装到「应用程序」

    private var installPath: String {
        (NSHomeDirectory() as NSString).appendingPathComponent("Applications/余额兔.app")
    }

    @objc private func menuInstallToApplications() {
        let source = Bundle.main.bundlePath
        let destination = installPath
        let fileManager = FileManager.default
        do {
            try fileManager.createDirectory(atPath: (destination as NSString).deletingLastPathComponent,
                                            withIntermediateDirectories: true)
            if fileManager.fileExists(atPath: destination) {
                try fileManager.removeItem(atPath: destination)
            }
            try fileManager.copyItem(atPath: source, toPath: destination)
            if LoginItem.isEnabled() {
                LoginItem.disable()
                _ = LoginItem.enable(executable: destination + "/Contents/MacOS/BalancePet")
            }
            NSWorkspace.shared.open(URL(fileURLWithPath: destination))
            NSApp.terminate(nil)
        } catch {
            alert(title: "安装失败", message: error.localizedDescription)
        }
    }

    private func alert(title: String, message: String) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "好的")
        alert.runModal()
    }
}
