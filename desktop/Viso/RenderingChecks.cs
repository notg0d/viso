using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Reflection;

namespace Viso
{
    // Pixel regressions for real WPF content, not just empty placeholders.
    // Synthetic color bars exercise the same preview presentation as live frames.
    internal static class RenderingChecks
    {
        public static async Task Run(Window window, string output, Action<BitmapSource> setPreview, Action<bool> setEnrolling)
        {
            var failures = new List<string>();
            var results = new List<object>();
            var name = (TextBox)window.FindName("ProfileName");
            var viewport = (FrameworkElement)window.FindName("CameraViewport");
            string oldName = name.Text;
            double oldWidth = window.Width, oldHeight = window.Height;
            Motion.StopAll();
            try
            {
                foreach (int width in new[] { 1040, 780 })
                {
                    window.Width = width; window.Height = 900;
                    foreach (var size in new[] { new Size(960, 720), new Size(1280, 720), new Size(720, 1280) })
                    {
                        setPreview(ColorBars((int)size.Width, (int)size.Height));
                        await Layout(window);
                        foreach (double scale in new[] { 1.0, 1.5, 2.0 })
                        {
                            string label = "preview-" + width + "-" + size.Width + "x" + size.Height + "-" + (int)(scale * 100);
                            var bitmap = Capture(viewport, scale);
                            Save(bitmap, Path.Combine(output, label + ".png"));
                            var left = Pixel(bitmap, .1, .5); var center = Pixel(bitmap, .5, .5); var right = Pixel(bitmap, .9, .5);
                            bool mirrored = left.B > 180 && left.R < 80 && center.G > 180 && center.R < 80 && right.R > 180 && right.B < 80;
                            // Samples throughout the circle must contain image data, not an empty wedge.
                            bool covered = true;
                            foreach (double x in new[] { .2, .5, .8 }) foreach (double y in new[] { .2, .5, .8 }) {
                                var color = Pixel(bitmap, x, y); covered &= Math.Max(color.R, Math.Max(color.G, color.B)) > 180 && color.A > 240;
                            }
                            var corner = Pixel(bitmap, .02, .02);
                            bool circular = Math.Max(corner.R, Math.Max(corner.G, corner.B)) < 80;
                            results.Add(Json.Data("case", label, "mirrored", mirrored, "covered", covered, "circular", circular));
                            if (!mirrored || !covered || !circular) failures.Add(label);
                        }
                    }
                    foreach (bool readOnly in new[] { false, true })
                    {
                        name.Text = "Uwaise"; name.CaretIndex = name.Text.Length;
                        setEnrolling(readOnly);
                        name.Focus();
                        await Layout(window);
                        Save(Capture((FrameworkElement)window.Content, 1), Path.Combine(output, "content-" + width + "-" + (readOnly ? "enrolling" : "typing") + ".png"));
                        foreach (double scale in new[] { 1.0, 1.5, 2.0 })
                        {
                            string label = "name-" + width + "-" + (readOnly ? "enrolling" : "typing") + "-" + (int)(scale * 100);
                            var bitmap = Capture(name, scale);
                            Save(bitmap, Path.Combine(output, label + ".png"));
                            int ink = CountTextPixels(bitmap, scale);
                            bool visible = ink > 70 * scale * scale;
                            bool state = name.IsEnabled && name.IsReadOnly == readOnly;
                            results.Add(Json.Data("case", label, "text_pixels", ink, "visible", visible, "correct_edit_state", state));
                            if (!visible || !state) failures.Add(label);
                        }
                    }
                }
                setPreview(null); setEnrolling(true);
                var ring = (EnrollmentRing)window.FindName("FaceRing");
                bool oldReduced = ring.ReducedMotion;
                ring.ReducedMotion = true; ring.Active = false;
                try {
                    foreach (int captured in new[] { 1, 5, 9, 13, 17 }) {
                        ring.Set(captured, 0, 0, 0, false); await Layout(window);
                        var bitmap = Capture(ring, 2); bool sectors = true;
                        for (int sector = 0; sector < 8; sector++) {
                            double angle = (270 + sector * 45 - 90) * Math.PI / 180;
                            double radius = .415 + 5.0 / 340;
                            var color = Pixel(bitmap, .5 + Math.Cos(angle) * radius, .5 + Math.Sin(angle) * radius);
                            bool green = color.G > 155 && color.G > color.B + 15;
                            bool blue = color.B > 180 && color.B > color.G + 50;
                            sectors &= green == (captured >= 10 + sector);
                            sectors &= blue == (captured >= 2 + sector && captured < 10 + sector);
                        }
                        string label = "circle-progress-" + captured;
                        Save(bitmap, Path.Combine(output, label + ".png"));
                        results.Add(Json.Data("case", label, "eight_sectors", sectors));
                        if (!sectors) failures.Add(label);
                    }
                    var bluePens = (Pen[])typeof(EnrollmentRing).GetField("bluePens", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(ring);
                    ring.Step = "up_left"; ring.Active = true; ring.Set(2, 10, -7, .7, false); await Layout(window);
                    var reused = typeof(EnrollmentRing).GetField("bluePens", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(ring);
                    bool cached = ReferenceEquals(bluePens, reused); foreach (var pen in bluePens) cached &= pen.IsFrozen && pen.Brush.IsFrozen;
                    bool staticMotion = !(bool)typeof(EnrollmentRing).GetField("running", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(ring);
                    ring.Set(17, 0, 0, 0, true);
                    bool complete = (double)ring.GetValue(EnrollmentRing.CompleteProperty) == 1;
                    results.Add(Json.Data("case", "circle-reduced-resources", "cached_frozen_pens", cached, "no_render_listener", staticMotion, "immediate_completion", complete));
                    if (!cached || !staticMotion || !complete) failures.Add("circle-reduced-resources");
                    // Identity requires both a frame count and elapsed time.
                    // Fast valid frames can exceed required=3 before 150 ms;
                    // their streak/required ratio must never overrun the palette.
                    ring.Step = "center"; ring.Active = true;
                    foreach (int streak in new[] { 0, 1, 3, 4, 5, 8, 12 }) {
                        ring.Set(0, 0, 0, streak / 3.0, false); await Layout(window);
                        var bitmap = Capture(ring, 2);
                        string label = "unlock-streak-" + streak;
                        Save(bitmap, Path.Combine(output, label + ".png"));
                        bool bounded = (double)ring.GetValue(EnrollmentRing.HoldProperty) >= 0 && (double)ring.GetValue(EnrollmentRing.HoldProperty) <= 1;
                        bool locked = (double)ring.GetValue(EnrollmentRing.CompleteProperty) == 0;
                        results.Add(Json.Data("case", label, "bounded_progress", bounded, "no_completion", locked));
                        if (!bounded || !locked) failures.Add(label);
                    }
                    foreach (var property in new[] { EnrollmentRing.HoldProperty, EnrollmentRing.CapturedProperty, EnrollmentRing.CompleteProperty }) {
                        int index = 0;
                        foreach (double value in new[] { -1.0, double.NaN, double.PositiveInfinity, double.NegativeInfinity, double.MaxValue }) {
                            ring.Set(0, 0, 0, 0, false); ring.SetValue(property, value); await Layout(window);
                            var bitmap = Capture(ring, 2);
                            double actual = (double)ring.GetValue(property), maximum = property == EnrollmentRing.CapturedProperty ? 17 : 1;
                            bool bounded = !double.IsNaN(actual) && !double.IsInfinity(actual) && actual >= 0 && actual <= maximum;
                            string label = "ring-bounds-" + property.Name.ToLowerInvariant() + "-" + index++;
                            Save(bitmap, Path.Combine(output, label + ".png"));
                            results.Add(Json.Data("case", label, "finite_bounded_progress", bounded));
                            if (!bounded) failures.Add(label);
                        }
                    }
                    bool oldMotionReduced = Motion.Reduced;
                    try {
                        Motion.Reduced = false; ring.ReducedMotion = false; ring.UpdateMotion();
                        foreach (int streak in new[] { 3, 4, 8, 12 }) {
                            ring.Set(0, 0, 0, streak / 3.0, false);
                            bool bounded = true;
                            for (int frame = 0; frame < 4; frame++) {
                                await Task.Delay(40); await Layout(window);
                                double hold = (double)ring.GetValue(EnrollmentRing.HoldProperty);
                                bounded &= hold >= 0 && hold <= 1;
                                var bitmap = Capture(ring, 2);
                                Save(bitmap, Path.Combine(output, "unlock-animated-" + streak + "-" + frame + ".png"));
                            }
                            string label = "unlock-animated-" + streak;
                            results.Add(Json.Data("case", label, "bounded_progress", bounded, "animation_enabled", Motion.Enabled, "sampled_frames", 4));
                            if (!bounded) failures.Add(label);
                        }
                        bool finiteTargets = true;
                        foreach (double value in new[] { -1.0, double.NaN, double.PositiveInfinity, double.NegativeInfinity, double.MaxValue }) {
                            ring.Set(value, value, value, value, false);
                            await Task.Delay(40); await Layout(window);
                            Capture(ring, 2);
                            foreach (var property in new[] { EnrollmentRing.HoldProperty, EnrollmentRing.CapturedProperty, EnrollmentRing.YawProperty, EnrollmentRing.PitchProperty }) {
                                double actual = (double)ring.GetValue(property);
                                finiteTargets &= !double.IsNaN(actual) && !double.IsInfinity(actual);
                            }
                        }
                        results.Add(Json.Data("case", "ring-animated-invalid-targets", "finite_targets", finiteTargets, "animation_enabled", Motion.Enabled));
                        if (!finiteTargets) failures.Add("ring-animated-invalid-targets");
                    } finally { Motion.Reduced = oldMotionReduced; ring.ReducedMotion = true; ring.UpdateMotion(); }
                } finally { ring.Reset(); ring.ReducedMotion = oldReduced; ring.UpdateMotion(); }
            }
            finally
            {
                setPreview(null); setEnrolling(false); name.Text = oldName;
                window.Width = oldWidth; window.Height = oldHeight;
            }
            File.WriteAllText(Path.Combine(output, "rendering.json"), Json.Encode(Json.Data("passed", failures.Count == 0, "cases", results, "failures", failures)));
            if (failures.Count != 0) throw new InvalidOperationException("Native rendering regressions: " + string.Join(", ", failures));
        }

        private static async Task Layout(Window window)
        {
            window.UpdateLayout();
            await window.Dispatcher.InvokeAsync(delegate { }, DispatcherPriority.ContextIdle);
        }
        private static BitmapSource ColorBars(int width, int height)
        {
            byte[] data = new byte[width * height * 4];
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int offset = (y * width + x) * 4, band = Math.Min(2, x * 3 / width);
                data[offset + (2 - band)] = 230; data[offset + 3] = 255;
            }
            var bitmap = BitmapSource.Create(width, height, 96, 96, PixelFormats.Bgra32, null, data, width * 4); bitmap.Freeze(); return bitmap;
        }
        private static RenderTargetBitmap Capture(FrameworkElement element, double scale)
        {
            double width = element.ActualWidth, height = element.ActualHeight;
            var root = (FrameworkElement)Window.GetWindow(element).Content;
            // Crop the composed window, including Viewbox scaling and layout offsets.
            var bounds = element.TransformToAncestor(root).TransformBounds(new Rect(0, 0, width, height));
            var visual = new DrawingVisual();
            using (var context = visual.RenderOpen()) {
                var brush = new VisualBrush(root) { ViewboxUnits = BrushMappingMode.Absolute, Viewbox = bounds, Stretch = Stretch.Fill };
                context.DrawRectangle(brush, null, new Rect(0, 0, width, height));
            }
            var bitmap = new RenderTargetBitmap((int)Math.Ceiling(width * scale), (int)Math.Ceiling(height * scale), 96 * scale, 96 * scale, PixelFormats.Pbgra32);
            bitmap.Render(visual); return bitmap;
        }
        private static Color Pixel(BitmapSource bitmap, double x, double y)
        {
            byte[] data = new byte[4];
            bitmap.CopyPixels(new Int32Rect((int)(x * bitmap.PixelWidth), (int)(y * bitmap.PixelHeight), 1, 1), data, 4, 0);
            return Color.FromArgb(data[3], data[2], data[1], data[0]);
        }
        private static int CountTextPixels(BitmapSource bitmap, double scale)
        {
            byte[] pixels = new byte[bitmap.PixelWidth * bitmap.PixelHeight * 4]; bitmap.CopyPixels(pixels, bitmap.PixelWidth * 4, 0);
            int count = 0;
            for (int y = (int)(5 * scale); y < bitmap.PixelHeight - 5 * scale; y++)
                for (int x = (int)(14 * scale); x < bitmap.PixelWidth - 14 * scale; x++) {
                    int offset = (y * bitmap.PixelWidth + x) * 4;
                    if (pixels[offset] > 150 && pixels[offset + 1] > 150 && pixels[offset + 2] > 150) count++;
                }
            return count;
        }
        private static void Save(BitmapSource bitmap, string path)
        {
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var file = File.Create(path)) encoder.Save(file);
        }
    }
}
