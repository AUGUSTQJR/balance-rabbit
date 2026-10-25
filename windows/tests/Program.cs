using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using BalanceRabbit;

internal static class Program
{
    private static int failures;

    private static void Check(bool condition, string name, string detail = "")
    {
        if (condition)
        {
            Console.WriteLine("PASS  " + name);
        }
        else
        {
            failures++;
            Console.WriteLine("FAIL  " + name + (detail.Length > 0 ? "  -> " + detail : ""));
        }
    }

    private static async Task<int> Main()
    {
        TestJson();
        await TestApi();

        Console.WriteLine();
        Console.WriteLine(failures == 0 ? "ALL TESTS PASSED" : failures + " TEST(S) FAILED");
        return failures == 0 ? 0 : 1;
    }

    private static void TestJson()
    {
        var obj = Json.Parse("{\"a\":1,\"b\":[true,false,null,\"x\\u4f60\"],\"c\":{\"d\":-2.5e2}}")
            as Dictionary<string, object>;
        Check(obj != null, "json: root object");
        Check(obj != null && obj.Count == 3, "json: key count");
        var arr = obj["b"] as List<object>;
        Check(arr != null && arr.Count == 4, "json: array length");
        Check(arr != null && (string)arr[3] == "x你", "json: unicode escape");
        var inner = obj["c"] as Dictionary<string, object>;
        Check(inner != null && Math.Abs((double)inner["d"] + 250) < 1e-9, "json: nested number");

        var page = UsagePage.From(Json.Parse(
            "{\"total\":123,\"items\":[{\"model\":\"m1\",\"created_at\":\"2026-10-19T10:00:00\"," +
            "\"charged_cny\":0.5,\"balance_cny\":88.25,\"input_tokens\":10,\"output_tokens\":20," +
            "\"cache_read_tokens\":3,\"cache_write_tokens\":4}]}"));
        Check(page.Total == 123, "json: page total");
        Check(page.Items.Count == 1 && page.Items[0].Model == "m1", "json: item model");
        Check(page.Items[0].Charged == 0.5 && page.Items[0].Balance == 88.25, "json: item money");
        Check(page.Items[0].InputTokens + page.Items[0].OutputTokens +
              page.Items[0].CacheReadTokens + page.Items[0].CacheWriteTokens == 37, "json: tokens");

        Check(APIClient.ParseTimestamp("2026-10-19T10:00:00") == new DateTime(2026, 10, 19, 10, 0, 0),
            "timestamp: seconds");
        Check(APIClient.ParseTimestamp("2026-10-19T10:00:00.123") == new DateTime(2026, 10, 19, 10, 0, 0, 123),
            "timestamp: millis");
        Check(APIClient.ParseTimestamp("garbage") == null, "timestamp: invalid");

        var balance = AccountBalance.From(Json.Parse(
            "{\"user_id\":132,\"balance_cny\":76.6517,\"currency\":\"CNY\",\"is_active\":true}"));
        Check(balance != null && Math.Abs(balance.Balance - 76.6517) < 1e-9, "account: balance");
        Check(balance.UserId == 132 && balance.IsActive == true, "account: user id / active");

        var spending = SpendingReport.From(Json.Parse(
            "{\"user_id\":132,\"balance_cny\":76.65,\"totals\":{\"request_count\":10," +
            "\"charged_cny\":1.5,\"recharged_cny\":20,\"input_tokens\":100,\"output_tokens\":20," +
            "\"cache_read_tokens\":3,\"cache_write_tokens\":4},\"days\":[{\"date\":\"2026-10-20\"," +
            "\"request_count\":6,\"charged_cny\":0.9,\"input_tokens\":50,\"output_tokens\":10," +
            "\"cache_read_tokens\":1,\"cache_write_tokens\":2}]}"));
        Check(spending != null && spending.RequestCount == 10, "spending: totals requests");
        Check(spending != null && Math.Abs(spending.Charged - 1.5) < 1e-9, "spending: totals charged");
        Check(spending != null && Math.Abs(spending.Recharged - 20) < 1e-9, "spending: recharged");
        Check(spending != null && spending.TotalsTokens == 127, "spending: totals tokens");
        Check(spending != null && spending.Days.Count == 1 &&
              spending.Days[0].Date == new DateTime(2026, 10, 20) &&
              spending.Days[0].Requests == 6, "spending: day bucket");

        var empty = Json.Parse("{}") as Dictionary<string, object>;
        Check(empty != null && empty.Count == 0, "json: empty object");
        try
        {
            Json.Parse("{bad}");
            Check(false, "json: malformed throws");
        }
        catch (JsonException)
        {
            Check(true, "json: malformed throws");
        }
    }

    private static async Task TestApi()
    {
        string key = ReadKey();
        if (string.IsNullOrEmpty(key))
        {
            Console.WriteLine("SKIP  api: no key found");
            return;
        }

        var client = new APIClient();
        Stats stats;
        try
        {
            stats = await client.LoadStatsAsync(key);
        }
        catch (Exception ex)
        {
            Check(false, "api: load stats", ex.Message);
            return;
        }

        Check(stats.Balance.HasValue, "api: balance present", "balance=" + stats.Balance);
        Check(stats.Daily.Count == 7, "api: 7 day buckets");
        Check(stats.WeekSpend >= stats.TodaySpend - 1e-9, "api: week >= today");
        Check(stats.WeekRequests >= stats.TodayRequests, "api: requests sane");
        Check(stats.WeekTokens >= 0, "api: tokens non-negative");
        Check(stats.TopModels.Count <= 3, "api: models capped");
        Check(stats.Daily.Last().Date == DateTime.Today, "api: last bucket is today");
        Check(stats.DataSource == "account", "api: account endpoints preferred", stats.DataSource);
        Check(stats.AccountUserId.HasValue, "api: account id");
        Check(stats.WeekRecharged >= 0, "api: recharged parsed");
        Check(stats.TotalRequests.HasValue, "api: total requests parsed");
        Check(stats.BalanceFromAPI, "api: balance from official API");

        Console.WriteLine();
        Console.WriteLine("REAL DATA: balance=" + stats.Balance +
                          " today=" + stats.TodaySpend.ToString("F4") +
                          " week=" + stats.WeekSpend.ToString("F4") +
                          " requests=" + stats.WeekRequests +
                          " tokens=" + stats.WeekTokens +
                          " total=" + stats.TotalRequests +
                          " partial=" + stats.Partial +
                          " source=" + stats.DataSource +
                          " account=" + (stats.AccountUserId.HasValue ? stats.AccountUserId.Value.ToString() : "nil") +
                          " inactive=" + stats.AccountInactive +
                          " recharged=" + stats.WeekRecharged.ToString("F2"));
        Console.WriteLine("MODELS: " + string.Join(", ",
            stats.TopModels.Select(m => m.Key + " x" + m.Value)));
        Console.WriteLine("DAILY:");
        foreach (DayStat day in stats.Daily)
        {
            Console.WriteLine("  " + day.Date.ToString("yyyy-MM-dd") +
                              "  spend=" + day.Spend.ToString("F4") + "  req=" + day.Requests);
        }
    }

    private static string ReadKey()
    {
        string env = Environment.GetEnvironmentVariable("RABBIT_API_KEY");
        if (!string.IsNullOrWhiteSpace(env)) return env.Trim();

        string path = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".dsh", ".credentials.yaml");
        if (!File.Exists(path)) return null;
        foreach (string rawLine in File.ReadAllLines(path))
        {
            string line = rawLine.Trim();
            if (!line.StartsWith("RABBIT_API_KEY:", StringComparison.Ordinal)) continue;
            return line.Substring("RABBIT_API_KEY:".Length).Trim().Trim('"', '\'');
        }
        return null;
    }
}
