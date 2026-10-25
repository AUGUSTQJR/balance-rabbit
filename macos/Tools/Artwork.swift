import Cocoa

/// 导出资源专用：把「蓝色圆环 · 弯弯眼」兔子按 160×160 设计画布画出来。
///
/// 注意：这份代码只被 Tools/main.swift 编译，**不参与 App 构建**。
/// App 运行时没有任何矢量绘制，只贴 `Assets/pet_sky.png`（低余额）或
/// `Assets/pet_sky_low.png`，所以三端（macOS / Windows / Linux）只要用同一份图，
/// 就不可能出现「某端耳朵错位」这类绘制差异。
enum PetArtwork {
    static let designSize: CGFloat = 160

    private static func rgb(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
        NSColor(calibratedRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: alpha)
    }

    // MARK: - 图标底

    static func drawIconBackground() {
        let rect = NSRect(x: 4, y: 4, width: 152, height: 152)
        let path = NSBezierPath(roundedRect: rect, xRadius: 36, yRadius: 36)
        let gradient = NSGradient(starting: rgb(0xF7FBFF), ending: rgb(0xE4F1FF))
        gradient?.draw(in: path, angle: -90)
    }

    // MARK: - 兔子（蓝色圆环 · 弯弯眼）

    static func drawPet(lowBalance: Bool) {
        let badgeRect = NSRect(x: 16.5, y: 19.5, width: 127, height: 127)
        let badge = NSBezierPath(ovalIn: badgeRect)

        // 圆框底 + 柔和投影
        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        shadow.shadowBlurRadius = 7
        shadow.shadowOffset = NSSize(width: 0, height: 3)
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.18)
        shadow.set()
        rgb(0xEAF6FD).setFill()
        badge.fill()
        NSGraphicsContext.restoreGraphicsState()

        // 蓝色渐变圆环
        let gradient = NSGradient(starting: rgb(0x4CC2E0), ending: rgb(0x2D80E0))
        gradient?.draw(in: badge, angle: 0)
        let inner = NSBezierPath(ovalIn: badgeRect.insetBy(dx: 3.4, dy: 3.4))
        rgb(0xEAF6FD).setFill()
        inner.fill()
        rgb(0x2F7DE1, 0.18).setStroke()
        let innerRing = NSBezierPath(ovalIn: badgeRect.insetBy(dx: 4.6, dy: 4.6))
        innerRing.lineWidth = 0.9
        innerRing.stroke()

        // 耳朵（在头后面）
        let earW: CGFloat = 16.5
        let earH: CGFloat = 52
        let headRect = NSRect(x: 36.5, y: 59, width: 87, height: 83)
        rgb(0xFFFFFF).setFill()
        capsule(center: NSPoint(x: 65.5, y: 54), width: earW, height: earH, rotation: -11).fill()
        capsule(center: NSPoint(x: 94.5, y: 54), width: earW, height: earH, rotation: 11).fill()
        rgb(0xF4C0CB).setFill()
        capsule(center: NSPoint(x: 65.5, y: 53.5), width: earW - 6.5, height: earH - 17, rotation: -11).fill()
        capsule(center: NSPoint(x: 94.5, y: 53.5), width: earW - 6.5, height: earH - 17, rotation: 11).fill()

        // 头 + 顶部高光 + 底部暖影
        let head = NSBezierPath(ovalIn: headRect)
        rgb(0xFFFFFF).setFill()
        head.fill()
        NSGraphicsContext.saveGraphicsState()
        head.addClip()
        NSGradient(starting: rgb(0xFFFFFF, 0.55), ending: rgb(0xFFFFFF, 0))?.draw(in: headRect, angle: -90)
        NSGradient(starting: rgb(0xEAC6A8, 0), ending: rgb(0xEAC6A8, 0.18))?
            .draw(in: headRect.insetBy(dx: 0, dy: -10), angle: -90)
        NSGraphicsContext.restoreGraphicsState()

        // 腮红
        rgb(0xF6AAB8, 0.37).setFill()
        NSBezierPath(ovalIn: NSRect(x: 43.5, y: 105.5, width: 15, height: 12.5)).fill()
        NSBezierPath(ovalIn: NSRect(x: 101.5, y: 105.5, width: 15, height: 12.5)).fill()

        // 弯弯眼
        rgb(0x3B2B26).setStroke()
        let eyeY: CGFloat = 96.5
        for cx in [CGFloat(64), CGFloat(96)] {
            let eye = NSBezierPath()
            eye.lineWidth = 2.2
            eye.lineCapStyle = .round
            eye.move(to: NSPoint(x: cx - 5.5, y: eyeY + 1.5))
            eye.curve(to: NSPoint(x: cx + 5.5, y: eyeY + 1.5),
                      controlPoint1: NSPoint(x: cx - 3.5, y: eyeY - 4.5),
                      controlPoint2: NSPoint(x: cx + 3.5, y: eyeY - 4.5))
            eye.stroke()
        }

        // 鼻子 + 嘴
        rgb(0xE28598).setFill()
        let nose = NSBezierPath()
        nose.move(to: NSPoint(x: 77, y: 106))
        nose.line(to: NSPoint(x: 83, y: 106))
        nose.line(to: NSPoint(x: 80, y: 109.5))
        nose.close()
        nose.fill()

        rgb(0x8A6552).setStroke()
        let mouth = NSBezierPath()
        mouth.lineWidth = 1.7
        mouth.lineCapStyle = .round
        mouth.move(to: NSPoint(x: 80, y: 109.5))
        mouth.line(to: NSPoint(x: 80, y: 111.5))
        mouth.move(to: NSPoint(x: 80, y: 111.5))
        mouth.curve(to: NSPoint(x: 73.5, y: 115.8),
                    controlPoint1: NSPoint(x: 77.2, y: 115),
                    controlPoint2: NSPoint(x: 74.6, y: 116.4))
        mouth.move(to: NSPoint(x: 80, y: 111.5))
        mouth.curve(to: NSPoint(x: 86.5, y: 115.8),
                    controlPoint1: NSPoint(x: 82.8, y: 115),
                    controlPoint2: NSPoint(x: 85.4, y: 116.4))
        mouth.stroke()

        // 低余额：圆框右上角感叹号
        if lowBalance {
            rgb(0xFF3B30).setFill()
            NSBezierPath(ovalIn: NSRect(x: 117, y: 25, width: 17, height: 17)).fill()
            let attributes: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: 11, weight: .bold),
                .foregroundColor: NSColor.white
            ]
            let mark = "!" as NSString
            let markSize = mark.size(withAttributes: attributes)
            mark.draw(at: NSPoint(x: 125.5 - markSize.width / 2, y: 33.5 - markSize.height / 2),
                      withAttributes: attributes)
        }
    }

    private static func capsule(center: NSPoint, width: CGFloat, height: CGFloat, rotation: CGFloat) -> NSBezierPath {
        let path = NSBezierPath(roundedRect: NSRect(x: -width / 2, y: -height / 2, width: width, height: height),
                                xRadius: width / 2,
                                yRadius: width / 2)
        var transform = AffineTransform(translationByX: center.x, byY: center.y)
        transform.rotate(byDegrees: rotation)
        path.transform(using: transform)
        return path
    }
}
