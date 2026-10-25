using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;

namespace BalanceRabbit
{
    /// <summary>与 macOS 版一致的配色与绘图小工具。</summary>
    public static class Paint
    {
        public static readonly Color Fur = Color.FromArgb(253, 248, 239);
        public static readonly Color FurShade = Color.FromArgb(240, 230, 216);
        public static readonly Color Pink = Color.FromArgb(246, 196, 196);
        public static readonly Color Ink = Color.FromArgb(52, 45, 40);
        public static readonly Color Card = Color.FromArgb(254, 252, 249);
        public static readonly Color Accent = Color.FromArgb(90, 87, 214);
        public static readonly Color LowRed = Color.FromArgb(230, 56, 47);
        public static readonly Color ChartGray = Color.FromArgb(191, 191, 201);

        public static readonly Color BlueDeep = Color.FromArgb(39, 96, 250);
        public static readonly Color BlueLight = Color.FromArgb(109, 205, 255);
        public static readonly Color Cyan = Color.FromArgb(156, 242, 255);

        public static Color Alpha(Color color, float alpha)
        {
            int a = (int)Math.Round(Math.Max(0, Math.Min(1, alpha)) * 255);
            return Color.FromArgb(a, color.R, color.G, color.B);
        }

        public static Font Font(float designSize, FontStyle style)
        {
            // 设计稿单位直接当像素用：避免高 DPI 下 GDI+ 按 Graphics.DpiY 二次放大字号，
            // 导致文字比设计稿大、行距被挤爆。
            return new Font(FontFamilyName(), designSize, style, GraphicsUnit.Pixel);
        }

        private static string family;

        public static string FontFamilyName()
        {
            if (family != null) return family;
            foreach (string candidate in new[] { "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimHei" })
            {
                try
                {
                    using (var test = new FontFamily(candidate))
                    {
                        family = candidate;
                        return family;
                    }
                }
                catch
                {
                    // 尝试下一个
                }
            }
            family = "Arial";
            return family;
        }

        public static GraphicsPath RoundedRect(RectangleF rect, float radius)
        {
            var path = new GraphicsPath();
            if (radius <= 0.1f)
            {
                path.AddRectangle(rect);
                return path;
            }
            float d = radius * 2;
            path.AddArc(rect.X, rect.Y, d, d, 180, 90);
            path.AddArc(rect.Right - d, rect.Y, d, d, 270, 90);
            path.AddArc(rect.Right - d, rect.Bottom - d, d, d, 0, 90);
            path.AddArc(rect.X, rect.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

    }

    public static class TextBlock
    {
        public static void Draw(Graphics g, string text, RectangleF rect, Font font, Color color,
            StringAlignment align = StringAlignment.Near, StringAlignment line = StringAlignment.Near,
            bool wrap = false)
        {
            using (var format = new StringFormat())
            {
                format.Alignment = align;
                format.LineAlignment = line;
                format.Trimming = wrap ? StringTrimming.Word : StringTrimming.EllipsisCharacter;
                format.FormatFlags = wrap ? 0 : StringFormatFlags.NoWrap;
                using (var brush = new SolidBrush(color))
                {
                    g.DrawString(text, font, brush, rect, format);
                }
            }
        }

        public static void DrawCentered(Graphics g, string text, RectangleF rect, Font font, Color color)
        {
            Draw(g, text, rect, font, color, StringAlignment.Center, StringAlignment.Center);
        }
    }

    public static class Format
    {
        public static string Money2(double value)
        {
            return "¥" + value.ToString("F2", System.Globalization.CultureInfo.InvariantCulture);
        }

        public static string MoneySmart(double value)
        {
            if (Math.Abs(value) < 1e-9) return "¥0";
            if (Math.Abs(value) < 0.01) return "¥" + value.ToString("F4", System.Globalization.CultureInfo.InvariantCulture);
            if (Math.Abs(value) < 1) return "¥" + value.ToString("F3", System.Globalization.CultureInfo.InvariantCulture);
            return "¥" + value.ToString("F2", System.Globalization.CultureInfo.InvariantCulture);
        }

        public static string Tokens(int value)
        {
            if (value >= 100000000) return (value / 100000000.0).ToString("F2", System.Globalization.CultureInfo.InvariantCulture) + " 亿";
            if (value >= 10000) return (value / 10000.0).ToString("F1", System.Globalization.CultureInfo.InvariantCulture) + " 万";
            return value.ToString();
        }

        public static string Time(DateTime date)
        {
            return date.ToString("HH:mm");
        }

        public static string ShortDate(DateTime date)
        {
            return date.ToString("M/d");
        }
    }
}
