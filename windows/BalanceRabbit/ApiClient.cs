using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Threading.Tasks;

namespace BalanceRabbit
{
    /// <summary>
    /// rabbitj.top（anyGPT）客户端。
    /// 优先官方账户接口（/v1/account/balance + /v1/account/spending + 最近 1~2 页流水），
    /// 接口不可用时回退旧的 /v1/usage 翻页聚合，余额兜底 /v1/balance。
    /// </summary>
    public sealed class APIClient
    {
        public const string DefaultBase = "https://www.rabbitj.top";

        /// <summary>服务器按 Asia/Shanghai 切天；固定 +08:00，避免本机时区不同导致“今日/近 7 天”错位。</summary>
        public static readonly TimeZoneInfo ServerTimeZone = TimeZoneInfo.CreateCustomTimeZone(
            "Asia/Shanghai (+08:00)", TimeSpan.FromHours(8), "Asia/Shanghai", "Asia/Shanghai");

        public static DateTime ServerToday()
        {
            return TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, ServerTimeZone).Date;
        }

        private const int PageLimit = 200;
        private const int MaxPages = 25;
        private const int DigestPages = 2;

        private static readonly HttpClient Http = CreateHttpClient();

        private static HttpClient CreateHttpClient()
        {
            try
            {
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            }
            catch
            {
                // 老系统上忽略
            }
            var client = new HttpClient();
            client.Timeout = TimeSpan.FromSeconds(25);
            client.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", "BalanceRabbit/1.2 (Windows)");
            return client;
        }

        private static readonly string[] DateFormats =
        {
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm:ss.fff",
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm:ss'Z'"
        };

        public static DateTime? ParseTimestamp(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return null;
            DateTime parsed;
            if (DateTime.TryParseExact(text.Trim(), DateFormats, CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out parsed))
            {
                return parsed;
            }
            if (DateTime.TryParse(text.Trim(), CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out parsed))
            {
                return parsed;
            }
            return null;
        }

        private async Task<object> GetJsonAsync(string url, string key)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Get, url))
            {
                request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + key);
                using (HttpResponseMessage response = await Http.SendAsync(request).ConfigureAwait(false))
                {
                    if ((int)response.StatusCode != 200) return null;
                    string body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                    try
                    {
                        return Json.Parse(body);
                    }
                    catch
                    {
                        return null;
                    }
                }
            }
        }

        // MARK: - 官方账户接口（2026-10 姜昊良提供）

        /// <summary>GET /v1/account/balance → user_id / balance_cny / is_active；失败返回 null。</summary>
        public async Task<AccountBalance> FetchAccountBalanceAsync(string key)
        {
            try
            {
                object root = await GetJsonAsync(DefaultBase + "/v1/account/balance", key)
                    .ConfigureAwait(false);
                return root == null ? null : AccountBalance.From(root);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>GET /v1/account/spending?from=YYYY-MM-DD&amp;to=YYYY-MM-DD（只统计 billed）。</summary>
        public async Task<SpendingReport> FetchSpendingAsync(string key, DateTime from, DateTime to)
        {
            try
            {
                string url = DefaultBase + "/v1/account/spending?from=" +
                             from.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) +
                             "&to=" + to.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                object root = await GetJsonAsync(url, key).ConfigureAwait(false);
                return root == null ? null : SpendingReport.From(root);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>最近 1~2 页流水：模型分布 + 累计请求数。失败时尽量返回已拿到的部分。</summary>
        private async Task<UsageDigest> FetchUsageDigestAsync(string key, int pages)
        {
            var digest = new UsageDigest();
            int offset = 0;
            for (int pageIndex = 0; pageIndex < Math.Max(1, pages); pageIndex++)
            {
                UsagePage page;
                try
                {
                    page = await FetchPageAsync(key, offset, PageLimit).ConfigureAwait(false);
                }
                catch
                {
                    break;
                }
                if (page.Items.Count == 0) break;
                if (pageIndex == 0) digest.Total = page.Total;
                foreach (UsageItem item in page.Items)
                {
                    if (string.IsNullOrEmpty(item.Model)) continue;
                    int count;
                    digest.Models.TryGetValue(item.Model, out count);
                    digest.Models[item.Model] = count + 1;
                }
                if (page.Items.Count < PageLimit) break;
                offset += PageLimit;
            }
            return digest;
        }

        /// <summary>兼容早期的 GET /v1/balance（网站预留路径，可能 404）；失败返回 null。</summary>
        public async Task<BalanceInfo> FetchBalanceAsync(string key)
        {
            try
            {
                object root = await GetJsonAsync(DefaultBase + "/v1/balance", key).ConfigureAwait(false);
                if (root == null) return null;
                var obj = JsonHelp.AsObject(root);
                if (obj == null) return null;
                double? balance = JsonHelp.GetDouble(obj, "balance_cny");
                if (!balance.HasValue) balance = JsonHelp.GetDouble(obj, "balance");
                if (!balance.HasValue) return null;
                var info = new BalanceInfo();
                info.Balance = balance.Value;
                info.UserId = JsonHelp.GetInt(obj, "user_id");
                if (!info.UserId.HasValue) info.UserId = JsonHelp.GetInt(obj, "account_user_id");
                return info;
            }
            catch
            {
                return null;
            }
        }

        public async Task<UsagePage> FetchPageAsync(string key, int offset, int limit)
        {
            string url = DefaultBase + "/v1/usage?limit=" + limit + "&offset=" + offset + "&status=billed";
            using (var request = new HttpRequestMessage(HttpMethod.Get, url))
            {
                request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + key);
                HttpResponseMessage response;
                try
                {
                    response = await Http.SendAsync(request).ConfigureAwait(false);
                }
                catch (TaskCanceledException)
                {
                    throw new ApiException("timeout", "请求超时，请检查网络");
                }
                catch (HttpRequestException ex)
                {
                    throw new ApiException("network", "网络请求失败：" + ex.Message);
                }

                using (response)
                {
                    if ((int)response.StatusCode != 200)
                        throw ApiException.Http((int)response.StatusCode);
                    string body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                    try
                    {
                        return UsagePage.From(Json.Parse(body));
                    }
                    catch (Exception ex)
                    {
                        throw ApiException.Decoding(ex.Message);
                    }
                }
            }
        }

        // MARK: - 汇总

        /// <summary>余额、今日/近 7 天花费、逐日柱状图、Token、充值、模型分布。</summary>
        public async Task<Stats> LoadStatsAsync(string key)
        {
            if (string.IsNullOrEmpty(key)) throw ApiException.MissingKey();

            Stats accountStats = await LoadStatsFromAccountAsync(key).ConfigureAwait(false);
            if (accountStats != null) return accountStats;
            return await LoadStatsFromUsageAsync(key).ConfigureAwait(false);
        }

        private async Task<Stats> LoadStatsFromAccountAsync(string key)
        {
            DateTime now = DateTime.Now;
            DateTime startOfToday = ServerToday();
            DateTime weekStart = startOfToday.AddDays(-6);

            Task<SpendingReport> spendingTask = FetchSpendingAsync(key, weekStart, startOfToday);
            Task<AccountBalance> accountTask = FetchAccountBalanceAsync(key);
            Task<UsageDigest> digestTask = FetchUsageDigestAsync(key, DigestPages);

            SpendingReport spending = await spendingTask.ConfigureAwait(false);
            AccountBalance account = await accountTask.ConfigureAwait(false);
            UsageDigest digest = await digestTask.ConfigureAwait(false);
            if (spending == null) return null;

            double? balance = spending.Balance;
            if (!balance.HasValue && account != null) balance = account.Balance;
            if (!balance.HasValue)
            {
                BalanceInfo legacy = await FetchBalanceAsync(key).ConfigureAwait(false);
                if (legacy != null) balance = legacy.Balance;
            }
            if (!balance.HasValue) return null;

            var stats = new Stats();
            stats.UpdatedAt = now;
            stats.DataSource = "account";
            stats.BalanceFromAPI = true;
            stats.Balance = balance;
            stats.AccountUserId = spending.UserId ?? (account != null ? account.UserId : null);
            stats.AccountInactive = account != null && account.IsActive == false;
            stats.WeekSpend = spending.Charged;
            stats.WeekRequests = spending.RequestCount;
            stats.WeekRecharged = spending.Recharged;
            stats.WeekTokens = spending.TotalsTokens;
            stats.TotalRequests = digest != null ? digest.Total : null;
            stats.BalanceAt = "account-api";

            var dayMap = new Dictionary<DateTime, DayStat>();
            foreach (SpendingDay day in spending.Days)
            {
                var bucket = new DayStat(day.Date);
                bucket.Spend = day.Spend;
                bucket.Requests = day.Requests;
                dayMap[day.Date.Date] = bucket;
            }

            for (int i = 0; i < 7; i++)
            {
                DateTime date = startOfToday.AddDays(i - 6).Date;
                DayStat day;
                stats.Daily.Add(dayMap.TryGetValue(date, out day) ? day : new DayStat(date));
            }

            DayStat today;
            stats.TodaySpend = dayMap.TryGetValue(startOfToday, out today) ? today.Spend : 0;
            stats.TodayRequests = dayMap.TryGetValue(startOfToday, out today) ? today.Requests : 0;

            var models = new List<KeyValuePair<string, int>>(digest != null
                ? digest.Models
                : new Dictionary<string, int>());
            models.Sort((a, b) =>
            {
                int cmp = b.Value.CompareTo(a.Value);
                if (cmp != 0) return cmp;
                return string.CompareOrdinal(a.Key, b.Key);
            });
            for (int i = 0; i < models.Count && i < 3; i++) stats.TopModels.Add(models[i]);

            return stats;
        }

        /// <summary>回退路径：老版本翻页聚合（只有 /v1/usage 可用时使用）。</summary>
        private async Task<Stats> LoadStatsFromUsageAsync(string key)
        {
            DateTime now = DateTime.Now;
            DateTime startOfToday = ServerToday();
            DateTime weekStart = startOfToday.AddDays(-6);

            var dayMap = new Dictionary<DateTime, DayStat>();
            for (int i = 0; i < 7; i++)
            {
                DateTime date = startOfToday.AddDays(i - 6);
                dayMap[date.Date] = new DayStat(date.Date);
            }

            BalanceInfo legacyBalance = await FetchBalanceAsync(key).ConfigureAwait(false);
            int? accountUserId = legacyBalance != null ? legacyBalance.UserId : null;

            var stats = new Stats();
            stats.UpdatedAt = now;
            stats.DataSource = "usage";
            stats.AccountUserId = accountUserId;

            var modelCounts = new Dictionary<string, int>(StringComparer.Ordinal);
            var userIds = new HashSet<int>();
            bool sawOtherAccount = false;
            int offset = 0;
            int pageIndex = 0;
            bool reachedOlder = false;
            double? latestBalance = null;
            string latestBalanceAt = null;

            while (!reachedOlder && pageIndex < MaxPages)
            {
                UsagePage page = await FetchPageAsync(key, offset, PageLimit).ConfigureAwait(false);
                if (page.Items.Count == 0) break;

                if (pageIndex == 0)
                {
                    stats.TotalRequests = page.Total;
                }

                foreach (UsageItem item in page.Items)
                {
                    if (item.UserId.HasValue)
                    {
                        userIds.Add(item.UserId.Value);
                        if (accountUserId.HasValue && item.UserId.Value != accountUserId.Value)
                        {
                            // 管理员 Key 会带回别人的流水：只统计自己的账户
                            sawOtherAccount = true;
                            continue;
                        }
                    }

                    DateTime? created = ParseTimestamp(item.CreatedAt);
                    if (!created.HasValue) continue;

                    if (!latestBalance.HasValue)
                    {
                        latestBalance = item.Balance;
                        latestBalanceAt = item.CreatedAt;
                    }

                    if (created.Value < weekStart)
                    {
                        reachedOlder = true;
                        continue;
                    }

                    DateTime dayKey = created.Value.Date;
                    DayStat day;
                    if (dayMap.TryGetValue(dayKey, out day))
                    {
                        day.Spend += item.Charged;
                        day.Requests += 1;
                    }

                    stats.WeekSpend += item.Charged;
                    stats.WeekRequests += 1;
                    stats.WeekTokens += item.InputTokens + item.OutputTokens
                                        + item.CacheReadTokens + item.CacheWriteTokens;
                    if (!string.IsNullOrEmpty(item.Model))
                    {
                        int count;
                        modelCounts.TryGetValue(item.Model, out count);
                        modelCounts[item.Model] = count + 1;
                    }
                }

                pageIndex++;
                offset += PageLimit;
                if (page.Items.Count < PageLimit) break;
            }

            if (!reachedOlder && pageIndex >= MaxPages) stats.Partial = true;

            if (!stats.AccountUserId.HasValue && userIds.Count == 1)
            {
                foreach (int only in userIds) stats.AccountUserId = only;
            }
            stats.MultipleAccounts = sawOtherAccount || userIds.Count > 1;
            if (stats.MultipleAccounts)
            {
                // 管理员 Key：总数是全站口径，和自己账户无关
                stats.TotalRequests = null;
            }

            if (legacyBalance != null)
            {
                stats.Balance = legacyBalance.Balance;
                stats.BalanceFromAPI = true;
            }
            else if (latestBalance.HasValue)
            {
                stats.Balance = latestBalance;
                stats.BalanceAt = latestBalanceAt;
            }

            if (!stats.Balance.HasValue) throw ApiException.NoRecords();

            DayStat today;
            if (dayMap.TryGetValue(startOfToday.Date, out today))
            {
                stats.TodaySpend = today.Spend;
                stats.TodayRequests = today.Requests;
            }

            for (int i = 0; i < 7; i++)
            {
                DateTime date = startOfToday.AddDays(i - 6).Date;
                DayStat stat;
                stats.Daily.Add(dayMap.TryGetValue(date, out stat) ? stat : new DayStat(date));
            }

            var models = new List<KeyValuePair<string, int>>(modelCounts);
            models.Sort((a, b) =>
            {
                int cmp = b.Value.CompareTo(a.Value);
                if (cmp != 0) return cmp;
                return string.CompareOrdinal(a.Key, b.Key);
            });
            for (int i = 0; i < models.Count && i < 3; i++) stats.TopModels.Add(models[i]);

            return stats;
        }

        private sealed class UsageDigest
        {
            public int? Total;
            public Dictionary<string, int> Models = new Dictionary<string, int>(StringComparer.Ordinal);
        }
    }
}
