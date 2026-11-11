using System;
using System.Linq;
using System.Reflection;
using System.Windows.Media.Imaging;

namespace Viso
{
    internal static class AppIcon
    {
        public static BitmapFrame Load()
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Viso.AppIcon.ico"))
            {
                if (stream == null) throw new InvalidOperationException("The Viso app icon is missing. Rebuild the complete desktop application.");
                var decoder = new IconBitmapDecoder(stream, BitmapCreateOptions.PreservePixelFormat, BitmapCacheOption.OnLoad);
                // Retain the decoder's full size inventory for Windows' small/big
                // window icons; use the largest frame for the high-DPI header.
                var frame = decoder.Frames.OrderByDescending(image => image.PixelWidth).First();
                frame.Freeze();
                return frame;
            }
        }
    }
}
