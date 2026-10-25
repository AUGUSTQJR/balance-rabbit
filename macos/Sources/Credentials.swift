import Cocoa

enum Credentials {
    static let keychainService = "top.rabbitj.balancepet"
    static let keychainAccount = "api-key"

    /// 优先级：环境变量 > 当前用户钥匙串。
    /// 刻意不再读取 ~/.dsh/.credentials.yaml 这类共享文件：
    /// 否则换人使用同一台电脑时会显示上一个使用者的余额。
    static func apiKey() -> String? {
        if let key = ProcessInfo.processInfo.environment["RABBIT_API_KEY"], !key.isEmpty {
            return key
        }
        return fromKeychain()
    }

    static var hasKey: Bool { apiKey() != nil }

    /// 形如 "…4590"，用于菜单里确认当前用的是谁的 Key
    static func keyHint() -> String? {
        guard let key = apiKey(), key.count >= 4 else { return apiKey() == nil ? nil : "…" }
        return "…" + String(key.suffix(4))
    }

    /// 只用于「首次填写 Key」时预填：从旧的共享配置文件里读到的 Key 不会静默生效，
    /// 必须在对话框里确认保存到本机钥匙串后才会使用。
    static func legacySharedKey() -> String? {
        let path = ("~/.dsh/.credentials.yaml" as NSString).expandingTildeInPath
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        for rawLine in text.split(separator: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            guard line.hasPrefix("RABBIT_API_KEY:") else { continue }
            var value = line.dropFirst("RABBIT_API_KEY:".count).trimmingCharacters(in: .whitespaces)
            value = value.trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            if !value.isEmpty { return value }
        }
        return nil
    }

    static func delete() {
        _ = run("/usr/bin/security",
                ["delete-generic-password", "-s", keychainService, "-a", keychainAccount])
    }

    static func fromKeychain() -> String? {
        let result = run("/usr/bin/security",
                         ["find-generic-password", "-s", keychainService, "-a", keychainAccount, "-w"])
        guard result.ok else { return nil }
        let value = result.output.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    static func save(_ key: String) -> String? {
        let result = run("/usr/bin/security",
                         ["add-generic-password", "-U", "-s", keychainService, "-a", keychainAccount, "-w", key])
        return result.ok ? nil : "保存到钥匙串失败：\(result.output)"
    }
}

enum LoginItem {
    static let label = "top.rabbitj.balancepet"

    static var plistPath: String {
        ("~/Library/LaunchAgents/\(label).plist" as NSString).expandingTildeInPath
    }

    static var executablePath: String {
        Bundle.main.executablePath ?? CommandLine.arguments[0]
    }

    static func isEnabled() -> Bool {
        FileManager.default.fileExists(atPath: plistPath)
    }

    @discardableResult
    static func enable(executable: String? = nil) -> String? {
        let target = executable ?? executablePath
        let directory = ("~/Library/LaunchAgents" as NSString).expandingTildeInPath
        try? FileManager.default.createDirectory(atPath: directory, withIntermediateDirectories: true)
        let plist = """
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>\(label)</string>
            <key>ProgramArguments</key>
            <array>
                <string>\(xmlEscape(target))</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>LimitLoadToSessionType</key>
            <string>Aqua</string>
            <key>ProcessType</key>
            <string>Interactive</string>
        </dict>
        </plist>
        """
        do {
            try plist.write(toFile: plistPath, atomically: true, encoding: .utf8)
        } catch {
            return "写入自启配置失败：\(error.localizedDescription)"
        }
        _ = run("/bin/launchctl", ["unload", plistPath])
        let result = run("/bin/launchctl", ["load", "-w", plistPath])
        return result.ok ? nil : "launchctl 执行失败：\(result.output)"
    }

    static func disable() {
        _ = run("/bin/launchctl", ["unload", plistPath])
        try? FileManager.default.removeItem(atPath: plistPath)
    }

    private static func xmlEscape(_ value: String) -> String {
        value.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}
