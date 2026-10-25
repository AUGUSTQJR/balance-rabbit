import Cocoa

/// 把设计稿渲染成固定的 PNG 资源（App 运行时不画任何东西，只贴这些图）。
///
/// 用法：./build/export-assets <Assets目录> <预览目录>
///   - Assets/pet_sky.png      正常状态（768×768，160 设计画布 × 4.8）
///   - Assets/pet_sky_low.png  低余额状态（带右上角红色 ! 徽章）
///   - <预览目录>/icon_1024.png 应用图标底图
final class ArtworkView: NSView {
    var lowBalance = false
    var iconMode = false

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        let scale = bounds.width / PetArtwork.designSize
        context.saveGState()
        context.scaleBy(x: scale, y: scale)
        if iconMode { PetArtwork.drawIconBackground() }
        PetArtwork.drawPet(lowBalance: lowBalance)
        context.restoreGState()
    }
}

private func writePNG(_ view: NSView, to path: String) {
    let width = Int(view.bounds.width.rounded())
    let height = Int(view.bounds.height.rounded())
    guard width > 0, height > 0,
          let rep = NSBitmapImageRep(bitmapDataPlanes: nil,
                                     pixelsWide: width,
                                     pixelsHigh: height,
                                     bitsPerSample: 8,
                                     samplesPerPixel: 4,
                                     hasAlpha: true,
                                     isPlanar: false,
                                     colorSpaceName: .deviceRGB,
                                     bytesPerRow: 0,
                                     bitsPerPixel: 0) else { return }
    rep.size = view.bounds.size
    view.cacheDisplay(in: view.bounds, to: rep)
    guard let data = rep.representation(using: .png, properties: [:]) else { return }
    try? data.write(to: URL(fileURLWithPath: path))
    print("  \(path)  \(width)×\(height)")
}

let arguments = CommandLine.arguments
let assetsDir = arguments.count > 1 ? arguments[1] : "Assets"
let previewDir = arguments.count > 2 ? arguments[2] : "build/preview"

_ = NSApplication.shared
NSApp.setActivationPolicy(.prohibited)

let fileManager = FileManager.default
try? fileManager.createDirectory(atPath: assetsDir, withIntermediateDirectories: true)
try? fileManager.createDirectory(atPath: previewDir, withIntermediateDirectories: true)

// 兔子静态图（768 = 160 × 4.8，Retina 下放到 320pt 也清晰）
for (name, low) in [("pet_sky", false), ("pet_sky_low", true)] {
    let view = ArtworkView(frame: NSRect(x: 0, y: 0, width: 768, height: 768))
    view.lowBalance = low
    writePNG(view, to: assetsDir + "/\(name).png")
}

// 应用图标底图（1024）
let iconView = ArtworkView(frame: NSRect(x: 0, y: 0, width: 1024, height: 1024))
iconView.iconMode = true
writePNG(iconView, to: previewDir + "/icon_1024.png")
