import Cocoa

/// 桌面兔子：只负责「贴图 + 交互」。
///
/// 形象本身是两张静态 PNG（`Assets/pet_sky.png` / `pet_sky_low.png`，由 Tools 里的
/// 设计稿导出，三端共用同一份图）。运行时不画任何矢量路径，所以不会出现
/// 「某端耳朵错位」这类平台绘制差异；也没有呼吸/眨眼/耳朵摆动等动画。
final class PetView: NSView {
    static let size = NSSize(width: 176, height: 176)

    var onActivate: (() -> Void)?
    var onContextMenu: ((NSEvent) -> Void)?
    var onMoved: ((NSPoint) -> Void)?
    var onResizeBy: ((CGFloat) -> Void)?
    var onDragBegan: (() -> Void)?
    var onDragEnded: (() -> Void)?

    /// 低余额时换成右上角带「!」的那张图
    var lowBalance = false {
        didSet { if lowBalance != oldValue { needsDisplay = true } }
    }

    private var dragStartMouse: NSPoint?
    private var dragStartOrigin: NSPoint = .zero
    private var dragged = false

    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // MARK: - 图片资源

    private static func loadImage(_ name: String) -> NSImage? {
        if let url = Bundle.main.url(forResource: name, withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            return image
        }
        // 开发期兜底：直接从工作区的 Assets 目录读（正常情况下图片已打进 .app）
        let fallback = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent("Assets/\(name).png")
        return NSImage(contentsOf: fallback)
    }

    private lazy var normalImage = PetView.loadImage("pet_sky")
    private lazy var lowImage = PetView.loadImage("pet_sky_low")

    // MARK: - 交互

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .pointingHand)
    }

    override func mouseDown(with event: NSEvent) {
        dragStartMouse = NSEvent.mouseLocation
        dragStartOrigin = window?.frame.origin ?? .zero
        dragged = false
        onDragBegan?()
    }

    override func mouseDragged(with event: NSEvent) {
        guard let start = dragStartMouse, let window = window else { return }
        let current = NSEvent.mouseLocation
        let dx = current.x - start.x
        let dy = current.y - start.y
        if abs(dx) > 2 || abs(dy) > 2 { dragged = true }
        guard dragged else { return }
        window.setFrameOrigin(NSPoint(x: dragStartOrigin.x + dx, y: dragStartOrigin.y + dy))
        onMoved?(window.frame.origin)
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

    override func scrollWheel(with event: NSEvent) {
        let flags = event.modifierFlags
        if flags.contains(.option) || flags.contains(.command) {
            onResizeBy?(event.scrollingDeltaY)
        } else {
            super.scrollWheel(with: event)
        }
    }

    // MARK: - 绘制（只有贴图）

    override func draw(_ dirtyRect: NSRect) {
        guard let image = lowBalance ? (lowImage ?? normalImage) : normalImage else { return }
        image.draw(in: bounds,
                   from: .zero,
                   operation: .sourceOver,
                   fraction: 1,
                   respectFlipped: true,
                   hints: [.interpolation: NSImageInterpolation.high])
    }
}
