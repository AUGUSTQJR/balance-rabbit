import Cocoa

// MARK: - 设置

extension Notification.Name {
    static let settingsChanged = Notification.Name("BalancePetSettingsChanged")
}

final class Settings {
    static let shared = Settings()
    private let defaults = UserDefaults.standard

    private func has(_ key: String) -> Bool { defaults.object(forKey: key) != nil }

    var refreshMinutes: Int {
        get { has("refreshMinutes") ? defaults.integer(forKey: "refreshMinutes") : 10 }
        set {
            defaults.set(newValue, forKey: "refreshMinutes")
            NotificationCenter.default.post(name: .settingsChanged, object: nil)
        }
    }

    var lowThreshold: Double {
        get { has("lowThreshold") ? defaults.double(forKey: "lowThreshold") : 20 }
        set {
            defaults.set(newValue, forKey: "lowThreshold")
            NotificationCenter.default.post(name: .settingsChanged, object: nil)
        }
    }

    var petX: Double? {
        get { has("petX") ? defaults.double(forKey: "petX") : nil }
        set { defaults.set(newValue, forKey: "petX") }
    }

    var petY: Double? {
        get { has("petY") ? defaults.double(forKey: "petY") : nil }
        set { defaults.set(newValue, forKey: "petY") }
    }

    var petSize: Double {
        get { has("petSize") ? defaults.double(forKey: "petSize") : 176 }
        set {
            defaults.set(newValue, forKey: "petSize")
            NotificationCenter.default.post(name: .settingsChanged, object: nil)
        }
    }

    var edgeDockEnabled: Bool {
        get { has("edgeDockEnabled") ? defaults.bool(forKey: "edgeDockEnabled") : true }
        set {
            defaults.set(newValue, forKey: "edgeDockEnabled")
            NotificationCenter.default.post(name: .settingsChanged, object: nil)
        }
    }

    var petHidden: Bool {
        get { defaults.bool(forKey: "petHidden") }
        set { defaults.set(newValue, forKey: "petHidden") }
    }

    var didWelcome: Bool {
        get { defaults.bool(forKey: "didWelcome") }
        set { defaults.set(newValue, forKey: "didWelcome") }
    }

    /// 上次运行的版本号，用来判断「刚安装 / 刚升级」→ 首启确认 Key 归属
    var lastRunVersion: String? {
        get { defaults.string(forKey: "lastRunVersion") }
        set { defaults.set(newValue, forKey: "lastRunVersion") }
    }
}

func appVersion() -> String {
    let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
    return version
}

// MARK: - 数据目录（写失败时降级）

enum AppStorage {
    /// 应用支持目录；不可写时依次降级到 Caches、临时目录，最后退回默认路径（内存模式）
    static let info: (directory: String, writable: Bool) = resolve()

    static var directory: String { info.directory }
    static var writable: Bool { info.writable }

    private static func resolve() -> (String, Bool) {
        let home = NSHomeDirectory()
        let candidates = [
            home + "/Library/Application Support/余额兔",
            home + "/Library/Caches/余额兔",
            NSTemporaryDirectory() + "余额兔"
        ]
        let fileManager = FileManager.default
        for path in candidates {
            try? fileManager.createDirectory(atPath: path, withIntermediateDirectories: true)
            let probe = path + "/.write-test-\(UUID().uuidString)"
            if fileManager.createFile(atPath: probe, contents: Data([0])) {
                try? fileManager.removeItem(atPath: probe)
                return (path, true)
            }
        }
        return (candidates[0], false)
    }
}

// MARK: - 进程执行

struct RunResult {
    let status: Int32
    let output: String
    var ok: Bool { status == 0 }
}

func run(_ launchPath: String, _ arguments: [String]) -> RunResult {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: launchPath)
    process.arguments = arguments
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe
    do {
        try process.run()
    } catch {
        return RunResult(status: -1, output: "\(error)")
    }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    return RunResult(status: process.terminationStatus, output: String(data: data, encoding: .utf8) ?? "")
}

// MARK: - 格式化

func money2(_ value: Double) -> String {
    String(format: "¥%.2f", value)
}

/// 小额消费保留更多小数位，避免都显示成 ¥0.00
func moneySmart(_ value: Double) -> String {
    if value == 0 { return "¥0" }
    if abs(value) < 0.01 { return String(format: "¥%.4f", value) }
    if abs(value) < 1 { return String(format: "¥%.3f", value) }
    return String(format: "¥%.2f", value)
}

func tokensText(_ value: Int) -> String {
    if value >= 100_000_000 { return String(format: "%.2f 亿", Double(value) / 100_000_000) }
    if value >= 10_000 { return String(format: "%.1f 万", Double(value) / 10_000) }
    return "\(value)"
}

func timeText(_ date: Date) -> String {
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    return f.string(from: date)
}

func shortDate(_ date: Date) -> String {
    let f = DateFormatter()
    f.dateFormat = "M/d"
    // 日柱的 date 是服务器（Asia/Shanghai）当天 0 点，按服务器时区显示才不会差一天
    f.timeZone = APIClient.serverTimeZone
    return f.string(from: date)
}

// MARK: - 视图截图（用于生成预览图 / 应用图标）

extension NSView {
    func pngData(scale: CGFloat, background: NSColor? = nil) -> Data? {
        let width = Int((bounds.width * scale).rounded())
        let height = Int((bounds.height * scale).rounded())
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
                                         bitsPerPixel: 0) else { return nil }
        rep.size = bounds.size

        if let background = background, let context = NSGraphicsContext(bitmapImageRep: rep) {
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = context
            context.cgContext.setFillColor(background.cgColor)
            context.cgContext.fill(CGRect(x: 0, y: 0, width: width, height: height))
            NSGraphicsContext.restoreGraphicsState()
        }

        cacheDisplay(in: bounds, to: rep)
        return rep.representation(using: .png, properties: [:])
    }
}

func renderSnapshots(to directory: String) {
    let fileManager = FileManager.default
    try? fileManager.createDirectory(atPath: directory, withIntermediateDirectories: true)

    // 兔子预览（直接贴 Assets 里的静态图片，正常 + 低余额两张）
    for (name, low) in [("pet", false), ("pet_low", true)] {
        let pet = PetView(frame: NSRect(origin: .zero, size: PetView.size))
        pet.lowBalance = low
        if let data = pet.pngData(scale: 3) {
            try? data.write(to: URL(fileURLWithPath: directory + "/\(name).png"))
        }
    }

    // 吸附指示器预览（只有箭头标签一种）
    for edge in [Edge.left, Edge.right] {
        let size = DockView.size(for: edge)
        let view = DockView(frame: NSRect(origin: .zero, size: size))
        view.edge = edge
        view.needsDisplay = true
        let name = "dock_arrowTab_\(edge == .left ? "left" : "right")"
        if let data = view.pngData(scale: 8) {
            try? data.write(to: URL(fileURLWithPath: directory + "/\(name).png"))
        }
    }

    // 气泡预览
    var sample = Stats()
    sample.balance = 88.6145
    sample.balanceAt = "2026-10-18T22:06:31"
    sample.todaySpend = 0.0321
    sample.todayRequests = 12
    sample.weekSpend = 0.4128
    sample.weekRequests = 46
    sample.weekTokens = 452_130
    sample.totalRequests = 1_284
    sample.updatedAt = Date()
    sample.topModels = [("deepseek-flash-1017", 32), ("claude-sonnet-5", 11)]
    let calendar = APIClient.serverCalendar
    let startOfToday = calendar.startOfDay(for: Date())
    let spends: [Double] = [0.021, 0, 0.053, 0.018, 0.084, 0.032, 0.021]
    sample.daily = (0..<7).map { index in
        let date = calendar.date(byAdding: .day, value: index - 6, to: startOfToday) ?? Date()
        return DayStat(date: date, spend: spends[index], requests: index * 3 + 2)
    }

    let bubble = BubbleView(frame: NSRect(origin: .zero, size: BubbleView.size))
    bubble.stats = sample
    if let data = bubble.pngData(scale: 2, background: NSColor(calibratedWhite: 0.86, alpha: 1)) {
        try? data.write(to: URL(fileURLWithPath: directory + "/bubble.png"))
    }

    // 低余额气泡预览
    var low = sample
    low.balance = 12.3
    let lowBubble = BubbleView(frame: NSRect(origin: .zero, size: BubbleView.size))
    lowBubble.stats = low
    if let data = lowBubble.pngData(scale: 2, background: NSColor(calibratedWhite: 0.86, alpha: 1)) {
        try? data.write(to: URL(fileURLWithPath: directory + "/bubble_low.png"))
    }

    // 柱状图悬停/选中预览
    var interactive = sample
    interactive.balance = 88.61
    interactive.accountUserId = 132
    let hoverBubble = BubbleView(frame: NSRect(origin: .zero, size: BubbleView.size))
    hoverBubble.stats = interactive
    hoverBubble.hoverDay = 4
    hoverBubble.selectedDay = 4
    if let data = hoverBubble.pngData(scale: 2, background: NSColor(calibratedWhite: 0.86, alpha: 1)) {
        try? data.write(to: URL(fileURLWithPath: directory + "/bubble_hover.png"))
    }

    // 多账户（站长 Key）提示预览
    var multi = sample
    multi.accountUserId = 132
    multi.multipleAccounts = true
    multi.totalRequests = nil
    let multiBubble = BubbleView(frame: NSRect(origin: .zero, size: BubbleView.size))
    multiBubble.stats = multi
    if let data = multiBubble.pngData(scale: 2, background: NSColor(calibratedWhite: 0.86, alpha: 1)) {
        try? data.write(to: URL(fileURLWithPath: directory + "/bubble_multi.png"))
    }
}

func runStatsCLI() {
    let semaphore = DispatchSemaphore(value: 0)
    Task {
        do {
            let stats = try await APIClient().loadStats()
            print("balance=\(stats.balance.map { String(format: "%.4f", $0) } ?? "nil")")
            print("today=\(String(format: "%.4f", stats.todaySpend)) week=\(String(format: "%.4f", stats.weekSpend))")
            print("weekRequests=\(stats.weekRequests) weekTokens=\(stats.weekTokens) total=\(stats.totalRequests.map(String.init) ?? "nil")")
            print("account=\(stats.accountUserId.map(String.init) ?? "nil") multiple=\(stats.multipleAccounts) fromAPI=\(stats.balanceFromAPI) source=\(stats.dataSource) inactive=\(stats.accountInactive) recharged=\(stats.weekRecharged)")
            for day in stats.daily {
                print("day \(shortDate(day.date)) spend=\(String(format: "%.4f", day.spend)) req=\(day.requests)")
            }
            for model in stats.topModels { print("model \(model.name) \(model.count)") }
        } catch {
            print("error=\((error as? LocalizedError)?.errorDescription ?? "\(error)")")
        }
        semaphore.signal()
    }
    semaphore.wait()
}
