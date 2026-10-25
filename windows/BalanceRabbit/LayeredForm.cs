using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace BalanceRabbit
{
    /// <summary>
    /// 逐像素透明、始终置顶、不抢焦点、不显示在任务栏的浮动窗口基类。
    /// 使用 UpdateLayeredWindow 呈现 32bpp ARGB 位图，与 macOS 版观感一致。
    /// </summary>
    public class LayeredForm : Form
    {
        private const int WS_EX_LAYERED = 0x00080000;
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_NOACTIVATE = 0x08000000;
        private const int WS_EX_TOPMOST = 0x00000008;

        private const int ULW_ALPHA = 0x00000002;
        private const byte AC_SRC_OVER = 0x00;
        private const byte AC_SRC_ALPHA = 0x01;

        public LayeredForm()
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            AutoScaleMode = AutoScaleMode.None;
            MinimizeBox = false;
            MaximizeBox = false;
            TopMost = true;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint, true);
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;
                cp.ExStyle |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST;
                return cp;
            }
        }

        protected override bool ShowWithoutActivation
        {
            get { return true; }
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            // 全部由 UpdateLayeredWindow 负责
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            // 同上
        }

        /// <summary>当前窗口所在显示器的缩放（96 dpi = 1.0）。</summary>
        public float DpiScale
        {
            get
            {
                try
                {
                    uint dpi = GetDpiForWindow(Handle);
                    if (dpi >= 48 && dpi <= 600) return dpi / 96f;
                }
                catch
                {
                    // 老系统（Win7）没有该 API，退回 1.0
                }
                return 1f;
            }
        }

        /// <summary>按目标屏幕矩形取 DPI 缩放（多显示器混合 DPI 布局时用，避免用错窗口当前所在屏幕）。</summary>
        public static float ScaleForRectangle(Rectangle screenRect)
        {
            try
            {
                var rect = new RECT
                {
                    Left = screenRect.Left,
                    Top = screenRect.Top,
                    Right = screenRect.Right,
                    Bottom = screenRect.Bottom
                };
                IntPtr monitor = MonitorFromRect(ref rect, 2); // MONITOR_DEFAULTTONEAREST
                uint dpiX, dpiY;
                if (GetDpiForMonitor(monitor, 0, out dpiX, out dpiY) == 0 && dpiX >= 48 && dpiX <= 600)
                {
                    return dpiX / 96f;
                }
            }
            catch
            {
                // Win7 没有 shcore，退回 1.0
            }
            return 1f;
        }

        /// <summary>按逻辑尺寸设置窗口大小（自动乘 DPI 缩放）。</summary>
        public void ApplyLogicalSize(int width, int height)
        {
            float scale = DpiScale;
            var size = new Size(
                Math.Max(1, (int)Math.Round(width * scale)),
                Math.Max(1, (int)Math.Round(height * scale)));
            if (Size != size) Size = size;
        }

        /// <summary>按逻辑位置设置窗口左上角（自动乘 DPI 缩放）。</summary>
        public void ApplyLogicalLocation(int x, int y)
        {
            float scale = DpiScale;
            Location = new Point((int)Math.Round(x * scale), (int)Math.Round(y * scale));
        }

        protected void Present(Bitmap bitmap)
        {
            if (bitmap == null) return;
            int width = bitmap.Width;
            int height = bitmap.Height;

            IntPtr screenDc = GetDC(IntPtr.Zero);
            IntPtr memDc = CreateCompatibleDC(screenDc);
            IntPtr hBitmap = IntPtr.Zero;
            IntPtr oldBitmap = IntPtr.Zero;
            try
            {
                // 用 32bpp top-down DIB 承载像素，直接拷贝预乘 alpha 数据，
                // 避免 GetHbitmap 在部分环境下丢失 alpha / 产生黑边。
                var info = new BITMAPINFO();
                info.bmiHeader.biSize = Marshal.SizeOf(typeof(BITMAPINFOHEADER));
                info.bmiHeader.biWidth = width;
                info.bmiHeader.biHeight = -height;
                info.bmiHeader.biPlanes = 1;
                info.bmiHeader.biBitCount = 32;
                info.bmiHeader.biCompression = 0; // BI_RGB
                IntPtr bits;
                hBitmap = CreateDIBSection(memDc, ref info, 0, out bits, IntPtr.Zero, 0);
                if (hBitmap == IntPtr.Zero || bits == IntPtr.Zero) return;
                oldBitmap = SelectObject(memDc, hBitmap);

                CopyPixels(bitmap, bits);

                var size = new SIZE(width, height);
                var src = new POINT(0, 0);
                var top = new POINT(Left, Top);
                var blend = new BLENDFUNCTION
                {
                    BlendOp = AC_SRC_OVER,
                    BlendFlags = 0,
                    SourceConstantAlpha = 255,
                    AlphaFormat = AC_SRC_ALPHA
                };
                UpdateLayeredWindow(Handle, screenDc, ref top, ref size, memDc, ref src,
                    0, ref blend, ULW_ALPHA);
            }
            finally
            {
                if (hBitmap != IntPtr.Zero)
                {
                    SelectObject(memDc, oldBitmap);
                    DeleteObject(hBitmap);
                }
                DeleteDC(memDc);
                ReleaseDC(IntPtr.Zero, screenDc);
            }
        }

        private static void CopyPixels(Bitmap bitmap, IntPtr destination)
        {
            int width = bitmap.Width;
            int height = bitmap.Height;
            System.Drawing.Imaging.BitmapData data = bitmap.LockBits(
                new Rectangle(0, 0, width, height),
                System.Drawing.Imaging.ImageLockMode.ReadOnly,
                System.Drawing.Imaging.PixelFormat.Format32bppPArgb);
            try
            {
                int rowBytes = width * 4;
                var row = new byte[rowBytes];
                for (int y = 0; y < height; y++)
                {
                    Marshal.Copy(IntPtr.Add(data.Scan0, y * data.Stride), row, 0, rowBytes);
                    Marshal.Copy(row, 0, IntPtr.Add(destination, y * rowBytes), rowBytes);
                }
            }
            finally
            {
                bitmap.UnlockBits(data);
            }
        }

        protected static Bitmap CreateCanvas(int pixelWidth, int pixelHeight, out Graphics graphics)
        {
            var bitmap = new Bitmap(Math.Max(1, pixelWidth), Math.Max(1, pixelHeight),
                System.Drawing.Imaging.PixelFormat.Format32bppPArgb);
            try
            {
                bitmap.SetResolution(96f, 96f);
            }
            catch
            {
                // 忽略
            }
            graphics = Graphics.FromImage(bitmap);
            graphics.Clear(Color.Transparent);
            graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
            graphics.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.HighQuality;
            graphics.CompositingQuality = System.Drawing.Drawing2D.CompositingQuality.HighQuality;
            graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAlias;
            return bitmap;
        }

        [DllImport("user32.dll")]
        private static extern uint GetDpiForWindow(IntPtr hwnd);

        [DllImport("user32.dll")]
        private static extern IntPtr MonitorFromRect(ref RECT rect, int flags);

        [DllImport("shcore.dll")]
        private static extern int GetDpiForMonitor(IntPtr hmonitor, int dpiType,
            out uint dpiX, out uint dpiY);

        [DllImport("user32.dll")]
        private static extern IntPtr GetDC(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateCompatibleDC(IntPtr hdc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr SelectObject(IntPtr hdc, IntPtr h);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteObject(IntPtr ho);

        [DllImport("gdi32.dll")]
        private static extern bool DeleteDC(IntPtr hdc);

        [DllImport("gdi32.dll")]
        private static extern IntPtr CreateDIBSection(IntPtr hdc, ref BITMAPINFO pbmi,
            uint usage, out IntPtr ppvBits, IntPtr hSection, uint offset);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool UpdateLayeredWindow(IntPtr hwnd, IntPtr hdcDst,
            ref POINT pptDst, ref SIZE psize, IntPtr hdcSrc, ref POINT pptSrc,
            int crKey, ref BLENDFUNCTION pblend, int dwFlags);

        [StructLayout(LayoutKind.Sequential)]
        private struct POINT
        {
            public int X;
            public int Y;

            public POINT(int x, int y)
            {
                X = x;
                Y = y;
            }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct SIZE
        {
            public int CX;
            public int CY;

            public SIZE(int cx, int cy)
            {
                CX = cx;
                CY = cy;
            }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BITMAPINFOHEADER
        {
            public int biSize;
            public int biWidth;
            public int biHeight;
            public short biPlanes;
            public short biBitCount;
            public int biCompression;
            public int biSizeImage;
            public int biXPelsPerMeter;
            public int biYPelsPerMeter;
            public int biClrUsed;
            public int biClrImportant;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BITMAPINFO
        {
            public BITMAPINFOHEADER bmiHeader;
            public int bmiColors;
        }

        [StructLayout(LayoutKind.Sequential, Pack = 1)]
        private struct BLENDFUNCTION
        {
            public byte BlendOp;
            public byte BlendFlags;
            public byte SourceConstantAlpha;
            public byte AlphaFormat;
        }
    }
}
