using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace Viso
{
    internal static class Motion
    {
        public static bool Reduced;
        private static readonly Dictionary<Tuple<DependencyObject, DependencyProperty>, Action> stops = new Dictionary<Tuple<DependencyObject, DependencyProperty>, Action>();
        public static bool Enabled { get { return !Reduced && SystemParameters.ClientAreaAnimation; } }
        public static void StopAll() { foreach (var stop in new List<Action>(stops.Values)) stop(); stops.Clear(); }
        public static void To(Animatable target, DependencyProperty property, double value, int milliseconds = 240)
        {
            double current = Convert.ToDouble(target.GetValue(property));
            var key = Tuple.Create((DependencyObject)target, property);
            Action previous; if (stops.TryGetValue(key, out previous)) { previous(); stops.Remove(key); }
            target.BeginAnimation(property, null);
            target.SetValue(property, value);
            if (!Enabled) return;
            var animation = new DoubleAnimation(current, value, TimeSpan.FromMilliseconds(milliseconds)) { EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut } };
            Action stop = delegate { target.BeginAnimation(property, null); };
            stops[key] = stop;
            animation.Completed += delegate { stop(); stops.Remove(key); };
            target.BeginAnimation(property, animation, HandoffBehavior.SnapshotAndReplace);
        }
        public static void Enter(FrameworkElement element)
        {
            var key = Tuple.Create((DependencyObject)element, UIElement.OpacityProperty);
            Action previous; if (stops.TryGetValue(key, out previous)) { previous(); stops.Remove(key); }
            element.BeginAnimation(UIElement.OpacityProperty, null);
            element.Opacity = 1;
            var offset = new TranslateTransform();
            element.RenderTransform = offset;
            if (!Enabled) return;
            offset.Y = 12;
            To(offset, TranslateTransform.YProperty, 0, 320);
            var animation = new DoubleAnimation(.25, 1, TimeSpan.FromMilliseconds(260));
            Action stop = delegate { element.BeginAnimation(UIElement.OpacityProperty, null); };
            stops[key] = stop;
            animation.Completed += delegate { stop(); stops.Remove(key); };
            element.BeginAnimation(UIElement.OpacityProperty, animation);
        }
        public static void Button(FrameworkElement button, double scale, int duration)
        {
            var transform = button.RenderTransform as ScaleTransform;
            if (transform == null) { transform = new ScaleTransform(1, 1); button.RenderTransform = transform; button.RenderTransformOrigin = new Point(.5, .5); }
            To(transform, ScaleTransform.ScaleXProperty, scale, duration);
            To(transform, ScaleTransform.ScaleYProperty, scale, duration);
        }
    }
}
