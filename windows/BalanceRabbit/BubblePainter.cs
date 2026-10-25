using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;

namespace BalanceRabbit
{
    /// <summary>余额气泡，尺寸与 macOS 版一致（300×282），坐标一一对应。</summary>
    public static class BubblePainter
    {
        public const float DesignWidth = 300f;
        public const float DesignHeight = 282f;

        // 图表几何（设计坐标）：窗口命中测试和绘制共用，保证点击位置一致
        public const float ChartLeft = 24f;
        public const float ChartWidth = 250f;
        public const float ChartTopOffset = 102f;   // 相对卡片顶部
        public const float ChartBarHeight = 40f;    // 基线相对图表顶部
        public const int DayCount = 7;

        public static void Draw(Graphics g, int pixelWidth, int pixelHeight,
            Stats stats, bool loading, float tailX, bool tailUp, double lowThreshold,
            int hoverDay = -1, int selectedDay = -1)
        {
            float scale = pixelWidth / DesignWidth;
            g.ScaleTransform(scale, scale);

            DrawCard(g, tailX, tailUp);
            RectangleF card = CardRect(tailUp);

            if (loading && (stats == null || !stats.Balance.HasValue))
            {
                // 首次加载 / 没有旧数据时才占满整块；有旧数据继续显示内容
                DrawLoading(g, card);
            }
            else if (stats != null && !stats.Balance.HasValue && !string.IsNullOrEmpty(stats.Error))
            {
                DrawError(g, card, stats.Error);
            }
            else if (stats != null)
            {
                DrawContent(g, card, stats, lowThreshold, hoverDay, selectedDay);
            }
            else
            {
                DrawEmpty(g, card);
            }
        }

        private static RectangleF CardRect(bool tailUp)
        {
            return new RectangleF(2, tailUp ? 20 : 2, 296, 256);
        }

        private static PointF[] TailPoints(float tailX, bool tailUp)
        {
            RectangleF card = CardRect(tailUp);
            const float half = 12f;
            const float length = 15f;
            if (tailUp)
            {
                return new[]
                {
                    new PointF(tailX - half, card.Top + 2),
                    new PointF(tailX + half, card.Top + 2),
                    new PointF(tailX, card.Top - length)
                };
            }
            return new[]
            {
                new PointF(tailX - half, card.Bottom - 2),
                new PointF(tailX + half, card.Bottom - 2),
                new PointF(tailX, card.Bottom + length)
            };
        }

        private static void DrawCard(Graphics g, float tailX, bool tailUp)
        {
            RectangleF card = CardRect(tailUp);
            PointF[] tail = TailPoints(tailX, tailUp);

            using (var union = new GraphicsPath())
            using (GraphicsPath rounded = Paint.RoundedRect(card, 18))
            {
                union.AddPath(rounded, false);
                union.AddPolygon(tail);

                // 柔和投影
                for (int i = 6; i >= 1; i--)
                {
                    using (var shadow = (GraphicsPath)union.Clone())
                    using (var matrix = new Matrix())
                    {
                        matrix.Translate(0, tailUp ? -1 : 1);
                        shadow.Transform(matrix);
                        int alpha = i == 6 ? 6 : 5;
                        using (var pen = new Pen(Color.FromArgb(alpha, 0, 0, 0), i * 2.2f))
                        {
                            pen.LineJoin = LineJoin.Round;
                            g.DrawPath(pen, shadow);
                        }
                    }
                }

                using (var fill = new SolidBrush(Paint.Card))
                {
                    g.FillPath(fill, union);
                }
                using (var border = new Pen(Color.FromArgb(16, 0, 0, 0), 1f))
                {
                    border.LineJoin = LineJoin.Round;
                    g.DrawPath(border, union);
                }
            }
        }

        private static void DrawContent(Graphics g, RectangleF card, Stats stats, double lowThreshold,
            int hoverDay, int selectedDay)
        {
            float top = card.Top;
            const float left = 24f;
            const float right = 274f;

            using (var labelFont = Paint.Font(11, FontStyle.Regular))
            using (var smallFont = Paint.Font(10, FontStyle.Regular))
            using (var balanceFont = Paint.Font(31, FontStyle.Bold))
            using (var bodyFont = Paint.Font(12, FontStyle.Regular))
            using (var lineFont = Paint.Font(11, FontStyle.Regular))
            using (var tinyFont = Paint.Font(9.5f, FontStyle.Regular))
            {
                TextBlock.Draw(g, "当前余额", new RectangleF(left, top + 16, 120, 20),
                    labelFont, Color.FromArgb(102, 102, 102));
                TextBlock.Draw(g, Format.Time(stats.UpdatedAt) + " 更新",
                    new RectangleF(right - 150, top + 17, 150, 18), smallFont,
                    Color.FromArgb(153, 153, 153), StringAlignment.Far);

                bool low = stats.IsLow(lowThreshold) && lowThreshold > 0;
                string balanceText = stats.Balance.HasValue ? Format.Money2(stats.Balance.Value) : "—";
                TextBlock.Draw(g, balanceText, new RectangleF(left - 2, top + 31, 250, 48),
                    balanceFont, low ? Paint.LowRed : Color.FromArgb(31, 31, 31));

                string overview = "今日 " + Format.MoneySmart(stats.TodaySpend) +
                                  "     近7天 " + Format.MoneySmart(stats.WeekSpend);
                TextBlock.Draw(g, overview, new RectangleF(left, top + 80, 250, 20),
                    bodyFont, Color.FromArgb(102, 102, 102));

                int activeDay = selectedDay >= 0 ? selectedDay : hoverDay;
                DrawChart(g, stats, top + ChartTopOffset, activeDay, top);

                using (var divider = new SolidBrush(Color.FromArgb(18, 0, 0, 0)))
                {
                    g.FillRectangle(divider, left, top + 174, right - left, 1);
                }

                TextBlock.Draw(g,
                    "Tokens " + Format.Tokens(stats.WeekTokens) + "   ·   近7天 " + stats.WeekRequests + " 次请求",
                    new RectangleF(left, top + 184, 250, 17), lineFont, Color.FromArgb(102, 102, 102));

                if (stats.TopModels.Count > 0)
                {
                    KeyValuePair<string, int> first = stats.TopModels[0];
                    TextBlock.Draw(g, "近期主力模型 " + first.Key + "（" + first.Value + " 次）",
                        new RectangleF(left, top + 203, 250, 17), lineFont, Color.FromArgb(102, 102, 102));
                }
                else
                {
                    TextBlock.Draw(g, "近 7 天暂无模型使用记录",
                        new RectangleF(left, top + 203, 250, 17), lineFont, Color.FromArgb(153, 153, 153));
                }

                using (var warningFont = Paint.Font(10.5f, FontStyle.Regular))
                {
                    string warning = null;
                    Color warningColor = Paint.LowRed;
                    if (low)
                    {
                        warning = "余额低于提醒阈值 " + Format.Money2(lowThreshold) + "，右键可打开充值";
                    }
                    else if (stats.MultipleAccounts)
                    {
                        warning = "当前 Key 可见多个账户，已按账户 #" +
                                  (stats.AccountUserId.HasValue
                                      ? stats.AccountUserId.Value.ToString()
                                      : "?") + " 过滤";
                        warningColor = Color.FromArgb(217, 128, 13);
                    }

                    if (warning != null)
                    {
                        using (var multiFont = Paint.Font(10f, FontStyle.Regular))
                        {
                            TextBlock.Draw(g, warning, new RectangleF(left, top + 222, right - left, 17),
                                stats.MultipleAccounts && !low && !stats.AccountInactive
                                    ? multiFont
                                    : warningFont,
                                warningColor);
                        }
                    }
                }

                // ---- 底部一行：当日详情 / 错误横幅 / 截断提示 / 累计请求 / 账户 id + 操作提示 ----
                string hint = "左键刷新 · 右键更多";
                SizeF hintSize = g.MeasureString(hint, tinyFont);
                float hintWidth = (float)Math.Ceiling(hintSize.Width) + 2f;
                float footerWidth = Math.Max(80f, (right - left) - hintWidth - 10f);

                string footerLine = null;
                Color footerColor = Color.FromArgb(153, 153, 153);
                Font footerFont = tinyFont;
                float footerHeight = 12f;

                if (activeDay >= 0 && stats.Daily != null && activeDay < stats.Daily.Count)
                {
                    DayStat active = stats.Daily[activeDay];
                    footerLine = Format.ShortDate(active.Date) + " 花费 " +
                                 Format.MoneySmart(active.Spend) + " · " + active.Requests + " 次";
                    footerColor = Paint.Accent;
                    footerHeight = 13f;
                }
                else if (!string.IsNullOrEmpty(stats.Error))
                {
                    footerLine = "⚠ 刷新失败：" + stats.Error;
                    footerColor = Paint.LowRed;
                }
                else if (stats.Partial)
                {
                    footerLine = "记录过多，近 7 天统计已截断";
                    footerColor = Color.FromArgb(217, 128, 13);
                }
                else if (stats.TotalRequests.HasValue)
                {
                    footerLine = "累计 " + stats.TotalRequests.Value + " 次请求";
                }
                else if (stats.AccountUserId.HasValue)
                {
                    footerLine = "账户 #" + stats.AccountUserId.Value;
                }

                if (footerLine != null)
                {
                    TextBlock.Draw(g, footerLine, new RectangleF(left, top + 240, footerWidth, footerHeight),
                        footerFont, footerColor);
                }
                TextBlock.Draw(g, hint,
                    new RectangleF(right - hintWidth - 2, top + 240, hintWidth + 2, 12), tinyFont,
                    Color.FromArgb(153, 153, 153), StringAlignment.Far);
            }
        }

        private static void DrawChart(Graphics g, Stats stats, float chartTop, int activeDay, float cardTop)
        {
            List<DayStat> daily = stats.Daily;
            if (daily == null || daily.Count != 7) return;

            const float left = ChartLeft;
            const float width = ChartWidth;
            float slot = width / DayCount;
            const float barWidth = 18f;
            float baseline = chartTop + 40f;
            // 柱子最高只占 28：上方留出「峰值」一行，避免和最高柱/其它文字重叠
            const float maxBarHeight = 28f;

            double maxSpend = 0;
            int peakIndex = 0;
            for (int i = 0; i < daily.Count; i++)
            {
                if (daily[i].Spend > maxSpend)
                {
                    maxSpend = daily[i].Spend;
                    peakIndex = i;
                }
            }
            if (maxSpend <= 0) maxSpend = 0.0001;

            int todayIndex = daily.Count - 1;

            using (var labelFont = Paint.Font(9, FontStyle.Regular))
            using (var peakFont = Paint.Font(9, FontStyle.Regular))
            {
                for (int index = 0; index < daily.Count; index++)
                {
                    DayStat day = daily[index];
                    float height = day.Spend <= 0 ? 2f : (float)Math.Max(3, maxBarHeight * (day.Spend / maxSpend));
                    float x = left + slot * index + (slot - barWidth) / 2f;
                    using (GraphicsPath bar = Paint.RoundedRect(
                        new RectangleF(x, baseline - height, barWidth, height), 4))
                    {
                        bool highlighted = index == activeDay;
                        Color color;
                        if (day.Spend <= 0) color = Color.FromArgb(26, 0, 0, 0);
                        else if (highlighted) color = Paint.Accent;
                        else if (index == todayIndex) color = Color.FromArgb(191, Paint.Accent);
                        else color = Paint.ChartGray;
                        using (var brush = new SolidBrush(color))
                        {
                            g.FillPath(brush, bar);
                        }
                    }

                    Color labelColor;
                    if (index == activeDay) labelColor = Color.FromArgb(64, 64, 64);
                    else if (index == todayIndex) labelColor = Color.FromArgb(102, 102, 102);
                    else labelColor = Color.FromArgb(158, 158, 158);
                    TextBlock.Draw(g, Format.ShortDate(day.Date),
                        new RectangleF(x - 8, baseline + 4, barWidth + 16, 12), labelFont,
                        labelColor, StringAlignment.Center);
                }

                if (maxSpend > 0.0001)
                {
                    // 与 macOS 一致：实测宽高，居中在最高柱正上方，再夹在卡片左右边界内
                    string peakText = "峰值 " + Format.MoneySmart(maxSpend);
                    SizeF peakSize = g.MeasureString(peakText, peakFont);
                    float peakWidth = Math.Min(width, (float)Math.Ceiling(peakSize.Width) + 2f);
                    float peakHeight = Math.Min(16f, Math.Max(12f,
                        (float)Math.Ceiling(peakSize.Height) + 1f));
                    float center = left + slot * peakIndex + slot / 2f;
                    float maxX = left + width - peakWidth;
                    float peakX = Math.Min(Math.Max(left, center - peakWidth / 2f), maxX);
                    float peakY = Math.Max(cardTop + 96f,
                        baseline - maxBarHeight - peakHeight - 2f);
                    TextBlock.Draw(g, peakText,
                        new RectangleF(peakX, peakY, peakWidth, peakHeight), peakFont,
                        Color.FromArgb(153, 153, 153), StringAlignment.Far);
                }
            }
        }

        private static void DrawLoading(Graphics g, RectangleF card)
        {
            float top = card.Top;
            using (var big = Paint.Font(26, FontStyle.Bold))
            using (var body = Paint.Font(12, FontStyle.Regular))
            {
                TextBlock.Draw(g, "查询中…", new RectangleF(24, top + 34, 250, 40), big,
                    Color.FromArgb(153, 153, 153));
                TextBlock.Draw(g, "正在读取最近 7 天的用量记录…", new RectangleF(24, top + 82, 250, 16),
                    body, Color.FromArgb(102, 102, 102));
            }
        }

        private static void DrawError(Graphics g, RectangleF card, string message)
        {
            float top = card.Top;
            using (var title = Paint.Font(22, FontStyle.Bold))
            using (var body = Paint.Font(12, FontStyle.Regular))
            using (var hint = Paint.Font(11, FontStyle.Regular))
            {
                TextBlock.Draw(g, "查询失败", new RectangleF(24, top + 34, 250, 32), title, Paint.LowRed);
                TextBlock.Draw(g, message, new RectangleF(24, top + 76, 250, 61), body,
                    Color.FromArgb(102, 102, 102), wrap: true);
                TextBlock.Draw(g, "右键 →「设置 API Key…」或「刷新余额」",
                    new RectangleF(24, top + 200, 250, 16), hint, Color.FromArgb(153, 153, 153));
            }
        }

        private static void DrawEmpty(Graphics g, RectangleF card)
        {
            float top = card.Top;
            using (var title = Paint.Font(22, FontStyle.Bold))
            using (var body = Paint.Font(12, FontStyle.Regular))
            {
                TextBlock.Draw(g, "点我查余额", new RectangleF(24, top + 40, 250, 36), title,
                    Color.FromArgb(31, 31, 31));
                TextBlock.Draw(g, "读取 rabbitj.top 账户余额与用量",
                    new RectangleF(24, top + 84, 250, 16), body, Color.FromArgb(102, 102, 102));
            }
        }
    }
}
