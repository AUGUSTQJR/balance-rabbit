using System;
using System.Collections.Generic;

namespace BalanceRabbit
{
    public sealed class DayStat
    {
        public DateTime Date;
        public double Spend;
        public int Requests;

        public DayStat(DateTime date)
        {
            Date = date.Date;
        }
    }

    public sealed class Stats
    {
        public double? Balance;
        public string BalanceAt;
        public double TodaySpend;
        public int TodayRequests;
        public double WeekSpend;
        public int WeekRequests;
        public int WeekTokens;
        public int? TotalRequests;
        public List<DayStat> Daily = new List<DayStat>();
        public List<KeyValuePair<string, int>> TopModels = new List<KeyValuePair<string, int>>();
        public DateTime UpdatedAt = DateTime.Now;
        public bool Partial;
        public string Error;
        /// <summary>当前 Key 所属账户 id（来自 /v1/balance；旧接口没有则为 null）。</summary>
        public int? AccountUserId;
        /// <summary>usage 返回里出现了多个账户（管理员 Key 视角）。</summary>
        public bool MultipleAccounts;
        /// <summary>余额是否来自官方账户接口（而不是流水推断）。</summary>
        public bool BalanceFromAPI;
        /// <summary>账号是否被停用（/v1/account/balance 的 is_active = false）。</summary>
        public bool AccountInactive;
        /// <summary>近 7 天充值金额（来自 /v1/account/spending）。</summary>
        public double WeekRecharged;
        /// <summary>本轮数据来源：account=新接口，usage=旧翻页回退。</summary>
        public string DataSource = "usage";

        public bool IsLow(double threshold)
        {
            return Balance.HasValue && Balance.Value < threshold;
        }
    }

    public sealed class BalanceInfo
    {
        public double Balance;
        public int? UserId;
    }

    /// <summary>GET /v1/account/balance 的解析结果。</summary>
    public sealed class AccountBalance
    {
        public double Balance;
        public int? UserId;
        public bool? IsActive;

        public static AccountBalance From(object root)
        {
            var obj = JsonHelp.AsObject(root);
            if (obj == null) return null;
            double? balance = JsonHelp.GetDouble(obj, "balance_cny");
            if (!balance.HasValue) balance = JsonHelp.GetDouble(obj, "balance");
            if (!balance.HasValue) return null;
            var info = new AccountBalance();
            info.Balance = balance.Value;
            info.UserId = JsonHelp.GetInt(obj, "user_id");
            info.IsActive = JsonHelp.GetBool(obj, "is_active");
            return info;
        }
    }

    /// <summary>GET /v1/account/spending 的单日明细。</summary>
    public sealed class SpendingDay
    {
        public DateTime Date;
        public int Requests;
        public double Spend;
        public int InputTokens;
        public int OutputTokens;
        public int CacheReadTokens;
        public int CacheWriteTokens;

        public int Tokens
        {
            get { return InputTokens + OutputTokens + CacheReadTokens + CacheWriteTokens; }
        }
    }

    /// <summary>GET /v1/account/spending 的解析结果。</summary>
    public sealed class SpendingReport
    {
        public int? UserId;
        public double? Balance;
        public int RequestCount;
        public double Charged;
        public double Recharged;
        public int TotalsTokens;
        public List<SpendingDay> Days = new List<SpendingDay>();

        public static SpendingReport From(object root)
        {
            var obj = JsonHelp.AsObject(root);
            if (obj == null) return null;
            var totals = JsonHelp.AsObject(Get(obj, "totals"));
            if (totals == null) return null;

            var report = new SpendingReport();
            report.UserId = JsonHelp.GetInt(obj, "user_id");
            report.Balance = JsonHelp.GetDouble(obj, "balance_cny");
            report.RequestCount = JsonHelp.GetInt(totals, "request_count") ?? 0;
            report.Charged = JsonHelp.GetDouble(totals, "charged_cny") ?? 0;
            report.Recharged = JsonHelp.GetDouble(totals, "recharged_cny") ?? 0;
            report.TotalsTokens = (JsonHelp.GetInt(totals, "input_tokens") ?? 0)
                                  + (JsonHelp.GetInt(totals, "output_tokens") ?? 0)
                                  + (JsonHelp.GetInt(totals, "cache_read_tokens") ?? 0)
                                  + (JsonHelp.GetInt(totals, "cache_write_tokens") ?? 0);

            var days = JsonHelp.AsArray(Get(obj, "days"));
            if (days != null)
            {
                foreach (object raw in days)
                {
                    var dayObj = JsonHelp.AsObject(raw);
                    if (dayObj == null) continue;
                    string text = JsonHelp.GetString(dayObj, "date");
                    DateTime date;
                    if (!DateTime.TryParseExact(text, "yyyy-MM-dd",
                            System.Globalization.CultureInfo.InvariantCulture,
                            System.Globalization.DateTimeStyles.None, out date))
                    {
                        continue;
                    }
                    var day = new SpendingDay();
                    day.Date = date.Date;
                    day.Requests = JsonHelp.GetInt(dayObj, "request_count") ?? 0;
                    day.Spend = JsonHelp.GetDouble(dayObj, "charged_cny") ?? 0;
                    day.InputTokens = JsonHelp.GetInt(dayObj, "input_tokens") ?? 0;
                    day.OutputTokens = JsonHelp.GetInt(dayObj, "output_tokens") ?? 0;
                    day.CacheReadTokens = JsonHelp.GetInt(dayObj, "cache_read_tokens") ?? 0;
                    day.CacheWriteTokens = JsonHelp.GetInt(dayObj, "cache_write_tokens") ?? 0;
                    report.Days.Add(day);
                }
            }
            return report;
        }

        private static object Get(Dictionary<string, object> obj, string key)
        {
            object value;
            return obj.TryGetValue(key, out value) ? value : null;
        }
    }

    public sealed class UsageItem
    {
        public string Model;
        public string CreatedAt;
        public double Charged;
        public double? Balance;
        public int? UserId;
        public int InputTokens;
        public int OutputTokens;
        public int CacheReadTokens;
        public int CacheWriteTokens;

        public static UsageItem From(Dictionary<string, object> obj)
        {
            var item = new UsageItem();
            if (obj == null) return item;
            item.Model = JsonHelp.GetString(obj, "model");
            item.CreatedAt = JsonHelp.GetString(obj, "created_at");
            item.Charged = JsonHelp.GetDouble(obj, "charged_cny") ?? 0d;
            item.Balance = JsonHelp.GetDouble(obj, "balance_cny");
            item.UserId = JsonHelp.GetInt(obj, "user_id");
            item.InputTokens = JsonHelp.GetInt(obj, "input_tokens") ?? 0;
            item.OutputTokens = JsonHelp.GetInt(obj, "output_tokens") ?? 0;
            item.CacheReadTokens = JsonHelp.GetInt(obj, "cache_read_tokens") ?? 0;
            item.CacheWriteTokens = JsonHelp.GetInt(obj, "cache_write_tokens") ?? 0;
            return item;
        }
    }

    public sealed class UsagePage
    {
        public int? Total;
        public List<UsageItem> Items = new List<UsageItem>();

        public static UsagePage From(object root)
        {
            var page = new UsagePage();
            var obj = JsonHelp.AsObject(root);
            if (obj == null) throw new JsonException("expected object");
            page.Total = JsonHelp.GetInt(obj, "total");
            var items = JsonHelp.AsArray(Get(obj, "items"));
            if (items != null)
            {
                foreach (object raw in items)
                {
                    var itemObj = JsonHelp.AsObject(raw);
                    if (itemObj != null) page.Items.Add(UsageItem.From(itemObj));
                }
            }
            return page;
        }

        private static object Get(Dictionary<string, object> obj, string key)
        {
            object value;
            return obj.TryGetValue(key, out value) ? value : null;
        }
    }

    public sealed class ApiException : Exception
    {
        public readonly string Kind;

        public ApiException(string kind, string message) : base(message)
        {
            Kind = kind;
        }

        public static ApiException MissingKey()
        {
            return new ApiException("missingKey", "未找到 API Key");
        }

        public static ApiException Http(int code)
        {
            return new ApiException("http", "接口返回 HTTP " + code);
        }

        public static ApiException BadResponse()
        {
            return new ApiException("badResponse", "接口响应异常");
        }

        public static ApiException NoRecords()
        {
            return new ApiException("noRecords", "暂无已计费记录，无法推算余额");
        }

        public static ApiException Decoding(string message)
        {
            return new ApiException("decoding", "数据解析失败：" + message);
        }
    }

    // 兔子形象只有一套（蓝色圆环 · 弯弯眼），且是固定图片，见 PetImages.cs。
}
