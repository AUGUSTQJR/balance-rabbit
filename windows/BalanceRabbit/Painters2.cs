using System;
using System.Drawing;
using System.Drawing.Drawing2D;

namespace BalanceRabbit
{
    public enum DockEdge
    {
        Left,
        Right
    }

    /// <summary>吸附在屏幕左/右边缘时的「箭头标签」电子指示器（与 macOS 版默认样式一致）。</summary>
    public static class DockPainter
    {
        public const float Design = 80f;
        public const float DesignScale = 0.6f;
        public const float EdgeLine = 40f;
        public const float LogicalSize = Design * DesignScale; // 48

        public static void Draw(Graphics g, int pixelSize, DockEdge edge, double phase, bool hovering)
        {
            float scale = pixelSize / LogicalSize;
            g.ScaleTransform(scale, scale);
            g.ScaleTransform(DesignScale, DesignScale);

            if (edge == DockEdge.Right)
            {
                g.TranslateTransform(Design, 0);
                g.ScaleTransform(-1, 1);
            }

            const float half = Design / 2f;
            float bob = (float)((hovering ? 3.0 : 2.0) * Math.Sin(phase * 2.2));
            var tabRect = new RectangleF(EdgeLine - 4, half - 17 + bob, 34, 34);

            using (GraphicsPath tab = Paint.RoundedRect(tabRect, 15))
            {
                // 外发光
                using (var glow = new Pen(Color.FromArgb(hovering ? 150 : 110, Paint.BlueDeep), hovering ? 8f : 6f))
                {
                    glow.LineJoin = LineJoin.Round;
                    g.DrawPath(glow, tab);
                }

                // 主体渐变
                using (var brush = new LinearGradientBrush(
                    new RectangleF(tabRect.X - 1, tabRect.Y - 1, tabRect.Width + 2, tabRect.Height + 2),
                    Paint.BlueLight, Paint.BlueDeep, 65f))
                {
                    g.FillPath(brush, tab);
                }

                // 亮边 + 内侧高光
                using (var edgePen = new Pen(Color.FromArgb(178, Paint.Cyan), 1.2f))
                {
                    edgePen.LineJoin = LineJoin.Round;
                    g.DrawPath(edgePen, tab);
                }
                using (GraphicsPath inner = Paint.RoundedRect(
                    new RectangleF(tabRect.X + 3, tabRect.Y + 3, tabRect.Width - 6, tabRect.Height - 6), 12))
                using (var highlight = new Pen(Color.FromArgb(71, 255, 255, 255), 1f))
                {
                    g.DrawPath(highlight, inner);
                }

                // 白色箭头
                float arrowX = tabRect.X + tabRect.Width / 2f + 1 + bob;
                float midY = tabRect.Y + tabRect.Height / 2f;
                using (var arrowPen = new Pen(Color.White, 2.6f))
                {
                    arrowPen.StartCap = LineCap.Round;
                    arrowPen.EndCap = LineCap.Round;
                    arrowPen.LineJoin = LineJoin.Round;
                    g.DrawLines(arrowPen, new[]
                    {
                        new PointF(arrowX - 3, midY - 6),
                        new PointF(arrowX + 2, midY),
                        new PointF(arrowX - 3, midY + 6)
                    });
                }
            }
        }
    }
}
