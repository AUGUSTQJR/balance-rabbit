import Cocoa

/// 吸附在屏幕左/右边缘时显示的指示器：只有「箭头标签」这一种样式。
final class DockView: NSView {

    static let designSize = NSSize(width: 80, height: 80)
    static let designScale: CGFloat = 0.6
    /// 屏幕边缘在画布中的位置（设计稿坐标），左边一半藏在屏幕外
    static let edgeLineDesign: CGFloat = 40

    static func size(for edge: Edge) -> NSSize {
        NSSize(width: designSize.width * designScale, height: designSize.height * designScale)
    }

    static func hiddenThickness(for edge: Edge) -> CGFloat {
        edgeLineDesign * designScale
    }

    var edge: Edge = .left { didSet { needsDisplay = true } }

    var onActivate: (() -> Void)?
    var onContextMenu: ((NSEvent) -> Void)?
    var onHoverChanged: ((Bool) -> Void)?
    var onDragBegan: (() -> Void)?
    var onDragMove: ((NSPoint) -> Void)?
    var onDragEnded: (() -> Void)?

    private var phase: CGFloat = 0
    private var timer: Timer?
    private var hovering = false
    private var dragStartMouse: NSPoint?
    private var dragged = false

    override var isFlipped: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        let ticker = Timer(timeInterval: 1.0 / 30.0, target: self, selector: #selector(tick), userInfo: nil, repeats: true)
        ticker.tolerance = 0.01
        RunLoop.main.add(ticker, forMode: .common)
        timer = ticker
    }

    required init?(coder: NSCoder) { fatalError("not supported") }

    deinit { timer?.invalidate() }

    @objc private func tick() {
        guard let window = window, window.isVisible else { return }
        phase += 1.0 / 30.0
        needsDisplay = true
    }

    // MARK: - 交互

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: bounds,
                                       options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                                       owner: self,
                                       userInfo: nil))
    }

    override func mouseEntered(with event: NSEvent) {
        hovering = true
        needsDisplay = true
        onHoverChanged?(true)
    }

    override func mouseExited(with event: NSEvent) {
        hovering = false
        needsDisplay = true
        onHoverChanged?(false)
    }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .pointingHand)
    }

    override func mouseDown(with event: NSEvent) {
        dragStartMouse = NSEvent.mouseLocation
        dragged = false
        onDragBegan?()
    }

    override func mouseDragged(with event: NSEvent) {
        guard let start = dragStartMouse else { return }
        let current = NSEvent.mouseLocation
        let delta = NSPoint(x: current.x - start.x, y: current.y - start.y)
        if abs(delta.x) > 2 || abs(delta.y) > 2 { dragged = true }
        guard dragged else { return }
        onDragMove?(delta)
    }

    override func mouseUp(with event: NSEvent) {
        defer { dragStartMouse = nil }
        guard dragStartMouse != nil else { return }
        if dragged {
            onDragEnded?()
        } else {
            onActivate?()
        }
    }

    override func rightMouseDown(with event: NSEvent) {
        onContextMenu?(event)
    }

    // MARK: - 配色

    private let blueDeep = NSColor(calibratedRed: 0.153, green: 0.376, blue: 0.980, alpha: 1)
    private let blueLight = NSColor(calibratedRed: 0.427, green: 0.804, blue: 1.000, alpha: 1)
    private let cyan = NSColor(calibratedRed: 0.612, green: 0.949, blue: 1.000, alpha: 1)

    // MARK: - 绘制

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.setShouldAntialias(true)
        context.saveGState()
        context.scaleBy(x: DockView.designScale, y: DockView.designScale)
        if edge == .right {
            context.translateBy(x: DockView.designSize.width, y: 0)
            context.scaleBy(x: -1, y: 1)
        }
        drawArrowTab(center: NSPoint(x: DockView.edgeLineDesign, y: DockView.designSize.height / 2))
        context.restoreGState()
    }

    // MARK: 半露箭头标签

    private func drawArrowTab(center: NSPoint) {
        let bob = (hovering ? 3.0 : 2.0) * sin(phase * 2.2)
        let tabRect = NSRect(x: DockView.edgeLineDesign - 4, y: center.y - 17, width: 34, height: 34)
        let tab = NSBezierPath(roundedRect: tabRect, xRadius: 15, yRadius: 15)

        // 发光
        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        shadow.shadowColor = blueDeep.withAlphaComponent(hovering ? 0.72 : 0.5)
        shadow.shadowBlurRadius = hovering ? 10 : 7
        shadow.shadowOffset = NSSize(width: 0, height: 0)
        shadow.set()
        blueDeep.setFill()
        tab.fill()
        NSGraphicsContext.restoreGraphicsState()

        // 渐变
        NSGraphicsContext.saveGraphicsState()
        tab.addClip()
        let gradient = NSGradient(colors: [blueLight, blueDeep])
        gradient?.draw(in: tabRect, angle: -70)
        NSGraphicsContext.restoreGraphicsState()

        // 亮边 + 内侧高光
        cyan.withAlphaComponent(0.7).setStroke()
        tab.lineWidth = 1.2
        tab.stroke()
        NSColor.white.withAlphaComponent(0.28).setStroke()
        let highlight = NSBezierPath(roundedRect: tabRect.insetBy(dx: 3, dy: 3), xRadius: 12, yRadius: 12)
        highlight.lineWidth = 1
        highlight.stroke()

        // 箭头
        let arrowX = tabRect.midX + 1 + bob
        let arrow = NSBezierPath()
        arrow.lineWidth = 2.6
        arrow.lineCapStyle = .round
        arrow.lineJoinStyle = .round
        arrow.move(to: NSPoint(x: arrowX - 3, y: tabRect.midY - 6))
        arrow.line(to: NSPoint(x: arrowX + 2, y: tabRect.midY))
        arrow.line(to: NSPoint(x: arrowX - 3, y: tabRect.midY + 6))
        NSColor.white.setStroke()
        arrow.stroke()
    }
}
