using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Reflection;

namespace BalanceRabbit
{
    /// <summary>
    /// 兔子形象图片（与 macOS 版共用的 Assets/pet_sky*.png，编译时内嵌进 exe）。
    /// 运行时不画任何东西，只把 PNG 按窗口像素尺寸缩放贴上去。
    /// </summary>
    public static class PetImages
    {
        private static Image normal;
        private static Image low;

        public static Image Normal
        {
            get { return normal ?? (normal = Load("pet_sky.png")); }
        }

        public static Image Low
        {
            get { return low ?? (low = Load("pet_sky_low.png")); }
        }

        private static Image Load(string name)
        {
            try
            {
                Assembly assembly = typeof(PetImages).Assembly;
                using (Stream stream = assembly.GetManifestResourceStream("BalanceRabbit." + name))
                {
                    if (stream == null) return null;
                    using (var loaded = new Bitmap(stream))
                    {
                        // Bitmap(Stream) 会依赖流生命周期；复制一份独立像素，避免流关闭后失效。
                        var copy = new Bitmap(loaded.Width, loaded.Height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
                        using (var g = Graphics.FromImage(copy))
                        {
                            g.CompositingMode = CompositingMode.SourceCopy;
                            g.DrawImage(loaded, new Rectangle(0, 0, copy.Width, copy.Height));
                        }
                        return copy;
                    }
                }
            }
            catch
            {
                // 图片损坏/资源缺失时退化为空白兔子（不影响余额功能）
                return null;
            }
        }
    }
}
