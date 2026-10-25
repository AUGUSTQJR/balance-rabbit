import Foundation

enum Edge {
    case left, right, bottom, top
}

// 兔子形象只有一套（蓝色圆环 · 弯弯眼），且是固定图片，见 Assets/pet_sky.png。
// 边缘吸附指示器只有一种（箭头标签），见 DockView。

struct DayStat {
    let date: Date
    var spend: Double = 0
    var requests: Int = 0
}

struct Stats {
    var balance: Double?
    var balanceAt: String?
    var todaySpend: Double = 0
    var todayRequests: Int = 0
    var weekSpend: Double = 0
    var weekRequests: Int = 0
    var weekTokens: Int = 0
    var totalRequests: Int?
    var daily: [DayStat] = []
    var topModels: [(name: String, count: Int)] = []
    var updatedAt: Date = Date()
    var partial = false
    var error: String?

    /// 账户 id（来自 /v1/balance，用于过滤多账户流水）
    var accountUserId: Int?
    /// 当前 Key 可见多个账户的流水（站长/管理员 Key）
    var multipleAccounts = false
    /// 余额是否来自官方余额接口（而不是流水推断）
    var balanceFromAPI = false
    /// /v1/account/balance 返回的 is_active == false。
    /// 注意：未知语义（实测有账号可用但返回 false），只做菜单里的中性提示，不当作停用告警。
    var accountInactive = false
    /// 近 7 天充值金额（来自 /v1/account/spending）
    var weekRecharged: Double = 0
    /// 本轮数据来源：account=新接口，usage=旧翻页回退
    var dataSource = "usage"

    var isLow: Bool {
        guard let b = balance else { return false }
        return b < Settings.shared.lowThreshold
    }
}

/// GET /v1/account/balance 的解析结果
struct AccountBalance {
    var userId: Int?
    var balance: Double
    var isActive: Bool?
}

/// GET /v1/account/spending 的逐日明细
struct SpendingDay {
    var date: Date
    var requests: Int
    var spend: Double
    var inputTokens: Int
    var outputTokens: Int
    var cacheReadTokens: Int
    var cacheWriteTokens: Int

    var tokens: Int { inputTokens + outputTokens + cacheReadTokens + cacheWriteTokens }
}

/// GET /v1/account/spending 的解析结果
struct SpendingReport {
    var userId: Int?
    var balance: Double?
    var requestCount: Int
    var charged: Double
    var recharged: Double
    var totalsTokens: Int
    var days: [SpendingDay]
}

struct UsageItem: Decodable {
    let model: String?
    let created_at: String?
    let charged_cny: Double?
    let balance_cny: Double?
    let input_tokens: Int?
    let output_tokens: Int?
    let cache_read_tokens: Int?
    let cache_write_tokens: Int?
    let user_id: Int?
    let account_user_id: Int?

    var userId: Int? { user_id ?? account_user_id }
}

struct UsagePage: Decodable {
    let total: Int?
    let items: [UsageItem]?
}

enum APIError: LocalizedError {
    case missingKey
    case http(Int)
    case badResponse
    case noRecords
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .missingKey: return "未找到 API Key"
        case .http(let code):
            switch code {
            case 401: return "API Key 未填写或已失效，请在菜单里重新填写"
            case 403: return "API Key 无效或账号已被停用，可换 Key 或联系站长确认"
            case 503: return "服务器数据查询异常，稍后会自动重试"
            default: return "接口返回 HTTP \(code)"
            }
        case .badResponse: return "接口响应异常"
        case .noRecords: return "暂无已计费记录，无法推算余额"
        case .decoding(let message): return "数据解析失败：\(message)"
        }
    }
}
