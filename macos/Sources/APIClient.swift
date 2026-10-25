import Foundation

struct APIClient {
    var base = "https://www.rabbitj.top"

    /// 服务器按 Asia/Shanghai 切天；客户端固定 +08:00，避免本机时区不同导致“今日/近 7 天”错位。
    static let serverTimeZone = TimeZone(secondsFromGMT: 8 * 3600)!

    static let serverCalendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = serverTimeZone
        calendar.locale = Locale(identifier: "en_US_POSIX")
        return calendar
    }()

    static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        formatter.timeZone = serverTimeZone
        return formatter
    }()

    static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = serverTimeZone
        return formatter
    }()

    private func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        return URLSession(configuration: configuration)
    }

    private func authorizedRequest(path: String,
                                   query: [URLQueryItem] = [],
                                   key: String) -> URLRequest? {
        var components = URLComponents(string: base + path)
        if !query.isEmpty { components?.queryItems = query }
        guard let url = components?.url else { return nil }
        var request = URLRequest(url: url)
        request.timeoutInterval = 20
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func getJSON(path: String,
                         query: [URLQueryItem] = [],
                         key: String) async -> Any? {
        guard let request = authorizedRequest(path: path, query: query, key: key) else { return nil }
        do {
            let (data, response) = try await session().data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return nil }
            return try JSONSerialization.jsonObject(with: data, options: [])
        } catch {
            return nil
        }
    }

    // MARK: - 官方账户接口（2026-10 姜昊良提供）

    /// GET /v1/account/balance → user_id / balance_cny / is_active
    func fetchAccountBalance(key: String) async -> AccountBalance? {
        guard let object = await getJSON(path: "/v1/account/balance", key: key),
              let dict = object as? [String: Any],
              let balance = APIClient.number(dict["balance_cny"]) ?? APIClient.number(dict["balance"]) else {
            return nil
        }
        return AccountBalance(userId: APIClient.integer(dict["user_id"]),
                              balance: balance,
                              isActive: dict["is_active"] as? Bool)
    }

    /// GET /v1/account/spending?from=YYYY-MM-DD&to=YYYY-MM-DD
    /// 逐日 + 区间汇总（只统计 billed），返回的 balance_cny 是实时余额。
    func fetchSpending(key: String, from: Date, to: Date) async -> SpendingReport? {
        let query = [
            URLQueryItem(name: "from", value: APIClient.dayFormatter.string(from: from)),
            URLQueryItem(name: "to", value: APIClient.dayFormatter.string(from: to))
        ]
        guard let object = await getJSON(path: "/v1/account/spending", query: query, key: key),
              let dict = object as? [String: Any],
              let totals = dict["totals"] as? [String: Any] else {
            return nil
        }

        var days: [SpendingDay] = []
        for item in dict["days"] as? [[String: Any]] ?? [] {
            guard let text = item["date"] as? String,
                  let date = APIClient.dayFormatter.date(from: text) else { continue }
            days.append(SpendingDay(date: APIClient.serverCalendar.startOfDay(for: date),
                                    requests: APIClient.integer(item["request_count"]) ?? 0,
                                    spend: APIClient.number(item["charged_cny"]) ?? 0,
                                    inputTokens: APIClient.integer(item["input_tokens"]) ?? 0,
                                    outputTokens: APIClient.integer(item["output_tokens"]) ?? 0,
                                    cacheReadTokens: APIClient.integer(item["cache_read_tokens"]) ?? 0,
                                    cacheWriteTokens: APIClient.integer(item["cache_write_tokens"]) ?? 0))
        }

        return SpendingReport(userId: APIClient.integer(dict["user_id"]),
                              balance: APIClient.number(dict["balance_cny"]),
                              requestCount: APIClient.integer(totals["request_count"]) ?? 0,
                              charged: APIClient.number(totals["charged_cny"]) ?? 0,
                              recharged: APIClient.number(totals["recharged_cny"]) ?? 0,
                              totalsTokens: (APIClient.integer(totals["input_tokens"]) ?? 0)
                                  + (APIClient.integer(totals["output_tokens"]) ?? 0)
                                  + (APIClient.integer(totals["cache_read_tokens"]) ?? 0)
                                  + (APIClient.integer(totals["cache_write_tokens"]) ?? 0),
                              days: days)
    }

    /// 兼容早期的 GET /v1/balance（Windows 记录里预接的路径）
    private func fetchLegacyBalance(key: String) async -> AccountBalance? {
        guard let object = await getJSON(path: "/v1/balance", key: key) else { return nil }
        return APIClient.parseBalance(object, depth: 0)
    }

    static func parseBalance(_ object: Any, depth: Int) -> AccountBalance? {
        guard depth < 3, let dict = object as? [String: Any] else { return nil }
        let balance = number(dict["balance_cny"]) ?? number(dict["balance"])
        let userId = integer(dict["user_id"]) ?? integer(dict["account_user_id"])
        if let balance = balance {
            return AccountBalance(userId: userId, balance: balance, isActive: nil)
        }
        if let nested = dict["data"] {
            return parseBalance(nested, depth: depth + 1)
        }
        return nil
    }

    private static func number(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? Int { return Double(value) }
        if let value = value as? NSNumber { return value.doubleValue }
        if let value = value as? String { return Double(value) }
        return nil
    }

    private static func integer(_ value: Any?) -> Int? {
        if let value = value as? Int { return value }
        if let value = value as? NSNumber { return value.intValue }
        if let value = value as? String { return Int(value) }
        return nil
    }

    // MARK: - 用量流水（只取最近几页：模型分布 + 累计请求数，不再翻 25 页）

    private func fetchPage(key: String, offset: Int, limit: Int) async throws -> UsagePage {
        guard let request = authorizedRequest(path: "/v1/usage",
                                              query: [
                                                URLQueryItem(name: "limit", value: "\(limit)"),
                                                URLQueryItem(name: "offset", value: "\(offset)"),
                                                URLQueryItem(name: "status", value: "billed")
                                              ],
                                              key: key) else {
            throw APIError.badResponse
        }

        let (data, response) = try await session().data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        guard http.statusCode == 200 else { throw APIError.http(http.statusCode) }

        do {
            return try JSONDecoder().decode(UsagePage.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }

    /// 最近 1~2 页流水：模型分布 + 全站累计请求数。失败返回 nil，不影响余额/花费展示。
    private func fetchUsageDigest(key: String, pages: Int) async -> (models: [String: Int], total: Int?)? {
        var models: [String: Int] = [:]
        var total: Int?
        var offset = 0
        let limit = 200
        for pageIndex in 0..<max(1, pages) {
            guard let page = try? await fetchPage(key: key, offset: offset, limit: limit) else {
                return pageIndex == 0 ? nil : (models, total)
            }
            if pageIndex == 0 { total = page.total }
            let items = page.items ?? []
            for item in items {
                if let model = item.model {
                    models[model, default: 0] += 1
                }
            }
            if items.count < limit { break }
            offset += limit
        }
        return (models, total)
    }

    // MARK: - 汇总

    /// 余额、今日/近 7 天花费、逐日柱状图、Token、充值、模型分布。
    /// 优先用官方账户接口（2 个请求 + 1~2 页流水）；接口不可用时回退旧的翻页聚合。
    func loadStats() async throws -> Stats {
        guard let key = Credentials.apiKey() else { throw APIError.missingKey }
        if let stats = await loadStatsFromAccount(key: key) {
            return stats
        }
        return try await loadStatsFromUsage(key: key)
    }

    private func loadStatsFromAccount(key: String) async -> Stats? {
        let calendar = APIClient.serverCalendar
        let now = Date()
        let startOfToday = calendar.startOfDay(for: now)
        guard let weekStart = calendar.date(byAdding: .day, value: -6, to: startOfToday) else { return nil }

        async let spendingTask = fetchSpending(key: key, from: weekStart, to: startOfToday)
        async let accountTask = fetchAccountBalance(key: key)
        async let digestTask = fetchUsageDigest(key: key, pages: 2)

        guard let spending = await spendingTask else {
            _ = await (accountTask, digestTask)
            return nil
        }
        let account = await accountTask
        let digest = await digestTask

        var fallbackBalance = account?.balance
        if fallbackBalance == nil {
            fallbackBalance = await fetchLegacyBalance(key: key)?.balance
        }
        guard let balance = spending.balance ?? fallbackBalance else { return nil }

        var stats = Stats()
        stats.updatedAt = now
        stats.dataSource = "account"
        stats.balanceFromAPI = true
        stats.balance = balance
        stats.accountUserId = spending.userId ?? account?.userId
        stats.accountInactive = account?.isActive == false
        stats.weekSpend = spending.charged
        stats.weekRequests = spending.requestCount
        stats.weekRecharged = spending.recharged
        stats.weekTokens = spending.totalsTokens
        stats.totalRequests = digest?.total
        stats.topModels = digest?.models
            .sorted { lhs, rhs in lhs.value == rhs.value ? lhs.key < rhs.key : lhs.value > rhs.value }
            .prefix(3)
            .map { ($0.key, $0.value) } ?? []

        var dayMap: [Date: DayStat] = [:]
        for day in spending.days {
            dayMap[day.date] = DayStat(date: day.date, spend: day.spend, requests: day.requests)
        }
        stats.daily = (0..<7).compactMap { index in
            guard let date = calendar.date(byAdding: .day, value: index - 6, to: startOfToday) else { return nil }
            let start = calendar.startOfDay(for: date)
            return dayMap[start] ?? DayStat(date: start)
        }
        stats.todaySpend = dayMap[startOfToday]?.spend ?? 0
        stats.todayRequests = dayMap[startOfToday]?.requests ?? 0
        return stats
    }

    /// 回退路径：老版本翻页聚合（只有 /v1/usage 可用时使用）
    private func loadStatsFromUsage(key: String) async throws -> Stats {
        let calendar = APIClient.serverCalendar
        let now = Date()
        let startOfToday = calendar.startOfDay(for: now)
        guard let weekStart = calendar.date(byAdding: .day, value: -6, to: startOfToday) else {
            throw APIError.badResponse
        }

        let legacyBalance = await fetchLegacyBalance(key: key)
        let accountUserId = legacyBalance?.userId

        var dayMap: [Date: DayStat] = [:]
        for index in 0..<7 {
            if let date = calendar.date(byAdding: .day, value: index - 6, to: startOfToday) {
                let start = calendar.startOfDay(for: date)
                dayMap[start] = DayStat(date: start)
            }
        }

        var stats = Stats()
        stats.updatedAt = now
        stats.dataSource = "usage"
        stats.accountUserId = accountUserId
        var modelCounts: [String: Int] = [:]
        var offset = 0
        let limit = 200
        let maxPages = 25
        var pageIndex = 0
        var reachedOlder = false
        var latestBalance: Double?
        var latestBalanceAt: String?
        var seenUserIds: Set<Int> = []
        var sawOtherAccount = false

        while !reachedOlder && pageIndex < maxPages {
            let page = try await fetchPage(key: key, offset: offset, limit: limit)
            let items = page.items ?? []
            if items.isEmpty { break }

            if pageIndex == 0 {
                stats.totalRequests = page.total
            }

            for item in items {
                if let userId = item.userId {
                    seenUserIds.insert(userId)
                    if let me = accountUserId, userId != me {
                        sawOtherAccount = true
                        continue
                    }
                }

                guard let text = item.created_at,
                      let date = APIClient.dateFormatter.date(from: text) else { continue }

                if latestBalance == nil {
                    latestBalance = item.balance_cny
                    latestBalanceAt = item.created_at
                }
                if date < weekStart {
                    reachedOlder = true
                    continue
                }
                let day = calendar.startOfDay(for: date)
                let charged = item.charged_cny ?? 0
                if var dayStat = dayMap[day] {
                    dayStat.spend += charged
                    dayStat.requests += 1
                    dayMap[day] = dayStat
                }
                stats.weekSpend += charged
                stats.weekRequests += 1
                stats.weekTokens += (item.input_tokens ?? 0)
                    + (item.output_tokens ?? 0)
                    + (item.cache_read_tokens ?? 0)
                    + (item.cache_write_tokens ?? 0)
                if let model = item.model {
                    modelCounts[model, default: 0] += 1
                }
            }

            pageIndex += 1
            offset += limit
            if items.count < limit { break }
        }

        if !reachedOlder && pageIndex >= maxPages { stats.partial = true }

        if accountUserId != nil {
            stats.multipleAccounts = sawOtherAccount
        } else if seenUserIds.count > 1 {
            stats.multipleAccounts = true
        }
        if stats.multipleAccounts {
            stats.totalRequests = nil
        }

        if let info = legacyBalance {
            stats.balance = info.balance
            stats.balanceFromAPI = true
        } else if let latest = latestBalance {
            stats.balance = latest
            stats.balanceAt = latestBalanceAt
        }

        guard stats.balance != nil else { throw APIError.noRecords }

        stats.todaySpend = dayMap[startOfToday]?.spend ?? 0
        stats.todayRequests = dayMap[startOfToday]?.requests ?? 0
        stats.daily = (0..<7).compactMap { index in
            guard let date = calendar.date(byAdding: .day, value: index - 6, to: startOfToday) else { return nil }
            let start = calendar.startOfDay(for: date)
            return dayMap[start] ?? DayStat(date: start)
        }
        stats.topModels = modelCounts
            .sorted { lhs, rhs in lhs.value == rhs.value ? lhs.key < rhs.key : lhs.value > rhs.value }
            .prefix(3)
            .map { ($0.key, $0.value) }
        return stats
    }
}
