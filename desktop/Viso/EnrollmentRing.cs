using System;
using System.Diagnostics;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace Viso
{
    // Glance-inspired ticks, measured head-turn band and directional light.
    // All progress is supplied by the recognition worker, never by a clock.
    public sealed class EnrollmentRing : FrameworkElement
    {
        public static readonly DependencyProperty CapturedProperty = Register("Captured");
        public static readonly DependencyProperty YawProperty = Register("Yaw");
        public static readonly DependencyProperty PitchProperty = Register("Pitch");
        public static readonly DependencyProperty CompleteProperty = Register("Complete");
        public static readonly DependencyProperty HoldProperty = Register("Hold");
        private static DependencyProperty Register(string name) { return DependencyProperty.Register(name, typeof(double), typeof(EnrollmentRing), new FrameworkPropertyMetadata(0.0, FrameworkPropertyMetadataOptions.AffectsRender)); }
        private readonly Stopwatch clock = Stopwatch.StartNew();
        private bool running;
        private bool active;
        private string step = "center";
        public bool ReducedMotion { get; set; }
        public string Step { get { return step; } set { step = value; InvalidateVisual(); } }
        public bool Active { get { return active; } set { active = value; UpdateMotion(); } }
        public EnrollmentRing()
        {
            IsHitTestVisible = false;
            Loaded += delegate { UpdateMotion(); };
            Unloaded += delegate { Stop(); };
        }
        public void UpdateMotion()
        {
            bool animate = active && IsLoaded && !ReducedMotion && Motion.Enabled;
            if (ReducedMotion || !Motion.Enabled)
                foreach (var property in new[] { CapturedProperty, YawProperty, PitchProperty, CompleteProperty, HoldProperty }) BeginAnimation(property, null);
            if (animate && !running) { CompositionTarget.Rendering += Frame; running = true; }
            if (!animate) Stop();
            InvalidateVisual();
        }
        private void Stop() { if (running) CompositionTarget.Rendering -= Frame; running = false; }
        private void Frame(object sender, EventArgs args) { InvalidateVisual(); }
        public void Set(double captured, double yaw, double pitch, double hold, bool complete)
        {
            Animate(CapturedProperty, captured, 300); Animate(YawProperty, yaw, 150); Animate(PitchProperty, pitch, 150);
            Animate(HoldProperty, hold, 120); Animate(CompleteProperty, complete ? 1 : 0, 420);
        }
        private void Animate(DependencyProperty property, double value, int duration)
        {
            double current = (double)GetValue(property);
            BeginAnimation(property, null);
            SetValue(property, value);
            if (ReducedMotion || !Motion.Enabled || Math.Abs(current - value) < .001) return;
            BeginAnimation(property, new DoubleAnimation(current, value, TimeSpan.FromMilliseconds(duration)) { EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }, FillBehavior = FillBehavior.Stop });
        }
        public void Reset() { Active = false; Step = "center"; Set(0, 0, 0, 0, false); }
        protected override void OnRender(DrawingContext dc)
        {
            base.OnRender(dc);
            double size = Math.Min(ActualWidth, ActualHeight), radius = size * .415;
            var center = new Point(ActualWidth / 2, ActualHeight / 2);
            double captured = (double)GetValue(CapturedProperty), complete = (double)GetValue(CompleteProperty);
            double yaw = (double)GetValue(YawProperty), pitch = (double)GetValue(PitchProperty), hold = (double)GetValue(HoldProperty);
            double t = clock.Elapsed.TotalSeconds;
            double breath = running ? .5 + .5 * Math.Sin(t * 2.5) : .5;
            double direction = Step == "left" ? 270 : Step == "right" ? 90 : Step == "down" ? 180 : 0;
            if (active && Step != "center")
            {
                double angle = (direction - 90) * Math.PI / 180;
                var glow = new RadialGradientBrush(Color.FromArgb((byte)(45 + breath * 22), 52, 153, 255), Colors.Transparent);
                dc.DrawEllipse(glow, null, new Point(center.X + Math.Cos(angle) * radius * .85, center.Y + Math.Sin(angle) * radius * .85), radius * .55, radius * .55);
            }
            double turn = Math.Atan2(-yaw, -pitch) * 180 / Math.PI;
            if (turn < 0) turn += 360;
            double magnitude = Math.Min(1, Math.Sqrt(yaw * yaw + pitch * pitch) / 16);
            for (int i = 0; i < 80; i++)
            {
                double degrees = i * 4.5, a = (degrees - 90) * Math.PI / 180;
                int sector = degrees >= 225 && degrees < 315 ? 2 : degrees >= 45 && degrees < 135 ? 3 : degrees >= 315 || degrees < 45 ? 4 : 5;
                double lit = Math.Max(0, Math.Min(1, captured - sector + 1));
                double delta = Math.Abs(degrees - turn); if (delta > 180) delta = 360 - delta;
                double tracking = Math.Max(0, 1 - delta / 27) * magnitude;
                double pulse = active && Step == "center" ? hold * .7 + breath * .15 : 0;
                double intensity = Math.Max(lit, Math.Max(tracking, pulse));
                double length = (6 + 8 * intensity) * size / 340;
                Color color = Color.FromRgb((byte)(83 - intensity * 31), (byte)(92 + intensity * 61), (byte)(105 + intensity * 150));
                var pen = new Pen(new SolidColorBrush(color), 2.6 * size / 340) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
                dc.PushOpacity(1 - complete);
                dc.DrawLine(pen, new Point(center.X + Math.Cos(a) * radius, center.Y + Math.Sin(a) * radius), new Point(center.X + Math.Cos(a) * (radius + length), center.Y + Math.Sin(a) * (radius + length)));
                dc.Pop();
            }
            if (complete > 0)
            {
                dc.PushOpacity(complete);
                dc.DrawEllipse(null, new Pen(new SolidColorBrush(Color.FromRgb(77, 191, 151)), 3), center, (radius + 7) * (.96 + complete * .04), (radius + 7) * (.96 + complete * .04));
                dc.Pop();
            }
        }
    }
}
