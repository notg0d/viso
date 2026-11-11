using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Win32;

namespace Viso
{
    internal sealed class MainWindow
    {
        private readonly Window window;
        private readonly string root;
        private readonly bool ephemeral, smoke;
        private EngineClient engine;
        private readonly DispatcherTimer timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(66) };
        private Dictionary<string, object> status = Json.Data();
        private readonly List<Dictionary<string, object>> events = new List<Dictionary<string, object>>();
        private readonly List<string> images = new List<string>();
        private readonly List<BitmapSource> imagePreviews = new List<BitmapSource>();
        private readonly object previewGate = new object();
        private BitmapSource nextPreview;
        private int previewGeneration, cameraGeneration;
        private int epoch;
        private string page = "face", operation = "";
        private bool busy, ticking, cameraOn, closed, initialized;
        private int cameraIndex;
        public int ExitCode { get; private set; }
        private EnrollmentRing Ring { get { return Find<EnrollmentRing>("FaceRing"); } }
        private bool Ready { get { return status.Child("engine").Flag("ready"); } }
        private bool HasProfile { get { return status.Get("profile") != null; } }
        private string PreferencesPath { get { return Path.Combine(root, ".viso", "desktop.json"); } }
        private T Find<T>(string name) where T : class { return (T)window.FindName(name); }
        private void Text(string name, string text) { Find<TextBlock>(name).Text = text; }
        private void Show(string name, bool visible) { Find<UIElement>(name).Visibility = visible ? Visibility.Visible : Visibility.Collapsed; }
        private static Brush Brush(string color) { return new SolidColorBrush((Color)ColorConverter.ConvertFromString(color)); }

        public MainWindow(Window window, string root, bool ephemeral, bool smoke)
        {
            this.window = window; this.root = root; this.ephemeral = ephemeral; this.smoke = smoke;
            Wire();
            window.Loaded += async delegate { await Initialize(); };
            window.Closed += delegate { Close(); };
            window.StateChanged += async delegate { if (window.WindowState == WindowState.Minimized) await Suspend(); };
            window.PreviewKeyDown += async delegate(object sender, KeyEventArgs args) {
                if (args.Key == Key.Escape && operation != "saving" && operation != "finishing") { args.Handled = true; await Cancel(); }
                if (args.Key == Key.Tab && Keyboard.Modifiers == ModifierKeys.Control && !busy) {
                    string[] pages = { "face", "unlock", "lab", "activity", "settings" };
                    args.Handled = true; await Navigate(pages[(Array.IndexOf(pages, page) + 1) % pages.Length]);
                }
            };
            SystemParameters.StaticPropertyChanged += OnSystemSettings;
            SystemEvents.SessionSwitch += OnSessionSwitch;
            SystemEvents.PowerModeChanged += OnPowerModeChanged;
            timer.Tick += async delegate { PresentPreview(); await Tick(); };
        }

        private void Click(string name, Func<Task> action, bool guarded = true)
        {
            Find<Button>(name).Click += async delegate { if (guarded) await Run(action); else await action(); };
        }
        private void Wire()
        {
            Click("MinimizeButton", delegate { window.WindowState = WindowState.Minimized; return Task.FromResult(0); }, false);
            Click("MaximizeButton", delegate { window.WindowState = window.WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized; return Task.FromResult(0); }, false);
            Click("CloseButton", delegate { window.Close(); return Task.FromResult(0); }, false);
            Click("DismissNotice", delegate { Show("Notice", false); return Task.FromResult(0); }, false);
            foreach (var item in new[] { "Face", "Unlock", "Lab", "Activity", "Settings" })
            {
                string target = item.ToLowerInvariant();
                Click("Nav" + item, delegate { return Navigate(target); }, false);
            }
            Click("CameraButton", async delegate {
                if (cameraOn) { await StopCamera(); CaptureIdle(); } else await StartCamera(epoch);
            });
            Click("MainAction", async delegate {
                if (page == "face" && HasProfile) { await StopCamera(); SetPage("settings"); return; }
                int ticket = ++epoch;
                if (!cameraOn) await StartCamera(ticket);
                if (ticket != epoch || closed) return;
                if (page == "face")
                {
                    var result = await engine.Send("enrollment.start", Json.Data("name", Find<TextBox>("ProfileName").Text.Trim()));
                    if (ticket != epoch || closed) return;
                    operation = "enrollment"; Show("SuccessBadge", false); ApplyEnrollment(result.Child("enrollment")); Log("Guided face enrollment started.");
                }
                else
                {
                    var result = await engine.Send("attempt.start", Json.Data("threshold", Find<Slider>("Threshold").Value));
                    if (ticket != epoch || closed) return;
                    operation = "attempt"; Show("SuccessBadge", false); Ring.Set(0, 0, 0, 0, false); ApplyAttempt(result.Child("attempt")); Log("Live unlock test started.");
                }
                Ring.Active = true;
            });
            Click("CancelAction", Cancel, false);
            Click("InspectFrame", async delegate {
                var observation = await engine.Send("analyze"); ApplyObservation(observation);
                Text("CaptureFeedback", observation.Text("message")); Log("Camera frame inspected: " + observation.Text("message"));
            });
            Click("DeleteProfile", async delegate {
                if (MessageBox.Show(window, "Delete the face enrollment from this PC?", "Delete enrollment", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No) != MessageBoxResult.Yes) return;
                await StopCamera();
                if (!ephemeral && !smoke && SignInSettings.IsInstalled) Text("SignInStatus", await SignInSettings.Unlink());
                status = await engine.Send("profile.delete"); Log("Face enrollment deleted."); UpdateStatus(); CaptureIdle();
            });
            Click("ChooseImages", ChooseImages);
            Click("ClearImages", delegate { ClearImages(); return Task.FromResult(0); });
            Click("LabEnroll", async delegate {
                status = await engine.Send("image.enroll", Json.Data("name", Find<TextBox>("LabName").Text.Trim(), "images", images.ToArray()));
                Log("Enrolled " + status.Child("profile").Text("name") + " from image samples."); UpdateStatus(); Text("LabResult", "Profile saved. Use Unlock test for live blink verification.");
            });
            Click("LabInspect", async delegate {
                var result = await engine.Send("analyze", Json.Data("image", SelectedImage()));
                Text("LabResult", ObservationSummary(result)); Log("Image inspected: " + result.Text("message"));
            });
            Click("LabReject", async delegate {
                var result = await engine.Send("image.test", Json.Data("image", SelectedImage(), "threshold", Find<Slider>("Threshold").Value));
                Text("LabResult", "Simulator locked. " + result.Child("attempt").Text("message") + "\n" + ObservationSummary(result.Child("observation")));
                Log("Photo rejection test: simulator remains locked.");
            });
            Click("ExportActivity", delegate {
                var dialog = new SaveFileDialog { Filter = "JSON session|*.json", FileName = "viso-session-" + DateTime.Now.ToString("yyyy-MM-dd") + ".json" };
                if (dialog.ShowDialog(window) == true) File.WriteAllText(dialog.FileName, Json.Encode(Json.Data("app", "Viso", "mode", "sandbox", "exported_at", DateTime.UtcNow.ToString("o"), "events", events)));
                return Task.FromResult(0);
            });
            Click("ClearActivity", delegate { events.Clear(); RenderEvents(); return Task.FromResult(0); });
            Click("RefreshCameras", RefreshCameras);
            Find<TextBox>("SignInAccount").Text = Environment.UserName;
            Click("RefreshSignIn", async delegate { Text("SignInStatus", await SignInSettings.Status()); });
            Click("LinkSignIn", async delegate {
                var password = Find<PasswordBox>("SignInPassword");
                try {
                    await StopCamera();
                    string message = await SignInSettings.Link(root, Find<ComboBox>("SignInAccountKind").SelectedIndex == 1 ? "microsoft" : "local", Find<TextBox>("SignInAccount").Text, password.Password, cameraIndex);
                    Text("SignInStatus", message); Log("Windows face sign-in account link updated.");
                } finally { password.Clear(); }
            });
            Click("UnlinkSignIn", async delegate { Text("SignInStatus", await SignInSettings.Unlink()); Log("Windows face sign-in disabled for this account."); });
            Find<ComboBox>("ImagePicker").SelectionChanged += delegate {
                int index = Find<ComboBox>("ImagePicker").SelectedIndex;
                Find<Image>("LabPreview").Source = index >= 0 && index < imagePreviews.Count ? imagePreviews[index] : null;
                Text("LabResult", "Ready to inspect this photo."); UpdateControls();
            };
            Find<ComboBox>("CameraPicker").SelectionChanged += delegate { if (initialized) { cameraIndex = Math.Max(0, Find<ComboBox>("CameraPicker").SelectedIndex); SavePreferences(); } };
            Find<Slider>("Threshold").ValueChanged += delegate { Text("ThresholdValue", Find<Slider>("Threshold").Value.ToString("F2")); if (initialized) SavePreferences(); };
            Find<CheckBox>("ReduceMotion").Checked += delegate { UpdateMotion(); if (initialized) SavePreferences(); };
            Find<CheckBox>("ReduceMotion").Unchecked += delegate { UpdateMotion(); if (initialized) SavePreferences(); };
            Find<TextBox>("ProfileName").TextChanged += delegate { UpdateControls(); };
            Find<TextBox>("LabName").TextChanged += delegate { UpdateControls(); };
            foreach (var button in Descendants(window).OfType<Button>())
            {
                button.MouseEnter += delegate { if (button.IsEnabled) Motion.Button(button, 1.018, 100); };
                button.MouseLeave += delegate { Motion.Button(button, 1, 180); };
                button.PreviewMouseLeftButtonDown += delegate { Motion.Button(button, .972, 90); };
                button.PreviewMouseLeftButtonUp += delegate { Motion.Button(button, 1, 180); };
                button.LostMouseCapture += delegate { Motion.Button(button, 1, 180); };
            }
        }
        private static IEnumerable<DependencyObject> Descendants(DependencyObject parent)
        {
            foreach (var child in LogicalTreeHelper.GetChildren(parent).OfType<DependencyObject>()) { yield return child; foreach (var next in Descendants(child)) yield return next; }
        }

        private async Task Initialize()
        {
            try
            {
                if (!smoke && File.Exists(PreferencesPath))
                {
                    try {
                        var preferences = Json.Decode(File.ReadAllText(PreferencesPath));
                        if (preferences.Get("threshold") != null) Find<Slider>("Threshold").Value = Math.Max(.35, Math.Min(.9, preferences.Number("threshold")));
                        Find<CheckBox>("ReduceMotion").IsChecked = preferences.Flag("reduce_motion");
                        cameraIndex = Math.Max(0, Math.Min(32, (int)preferences.Number("camera_index")));
                    } catch { /* A malformed UI preference cannot affect profile storage. */ }
                }
                UpdateMotion(); SetPage("face");
                engine = new EngineClient(root, ephemeral || smoke);
                engine.Event += EngineEvent;
                // Let the window paint and discover devices while Python loads.
                // A slow DirectShow driver must not block the UI thread.
                var engineStatus = engine.Send("status");
                await RefreshCameras();
                status = await engineStatus;
                if (closed) return;
                initialized = true; UpdateStatus(); UpdateControls();
                await engine.WaitForModels();
                status = await engine.Send("status");
                if (closed) return;
                UpdateStatus(); UpdateControls();
                Log(Ready ? "Local recognition engine ready." : "Recognition engine needs attention.");
                if (smoke) await SmokeTest();
            }
            catch (Exception error) { if (smoke) { SmokeFail(error); return; } Fail(error); UpdateControls(); }
        }

        private async Task Run(Func<Task> action)
        {
            if (busy || closed) return;
            busy = true; Show("Notice", false); UpdateControls();
            try { await action(); }
            catch (OperationCanceledException) { }
            catch (Exception error) { if (!closed) Fail(error); }
            finally { busy = false; if (!closed) UpdateControls(); }
        }
        private void Fail(Exception error)
        {
            Show("Notice", true); Text("NoticeText", error.Message); Log(error.Message, "error"); Motion.Enter(Find<Border>("Notice"));
        }

        private void EngineEvent(Dictionary<string, object> message)
        {
            if (closed) return;
            if (message.Text("event") == "preview")
            {
                try
                {
                    BitmapSource frame = DecodeBitmap(Convert.FromBase64String(message.Text("image")), 720);
                    lock (previewGate) { nextPreview = frame; previewGeneration = (int)message.Number("generation"); }
                }
                catch { }
            }
            else if (message.Text("event") == "camera_error" || message.Text("event") == "engine_error")
            {
                window.Dispatcher.BeginInvoke(new Action(async delegate {
                    if (closed) return;
                    if (message.Text("event") == "camera_error" && !cameraOn) return;
                    await Suspend();
                    if (message.Text("event") == "engine_error") { status = Json.Data(); Text("EngineStatus", "Engine disconnected"); UpdateControls(); }
                    Fail(new IOException(message.Text("message")));
                }));
            }
        }
        private void PresentPreview()
        {
            BitmapSource preview = null;
            lock (previewGate) { if (cameraOn && previewGeneration == cameraGeneration) preview = nextPreview; nextPreview = null; }
            if (preview != null) SetPreview(preview);
        }
        private void SetPreview(BitmapSource frame)
        {
            Find<ImageBrush>("CameraPreview").ImageSource = frame;
            Show("FacePlaceholder", frame == null);
        }
        private async Task StartCamera(int ticket)
        {
            Text("CameraStatus", "Opening camera…");
            Dictionary<string, object> result;
            try { result = await engine.Send("camera.start", Json.Data("index", cameraIndex)); }
            catch { ClearPreview(); throw; }
            if (ticket != epoch || closed || window.WindowState == WindowState.Minimized) throw new OperationCanceledException();
            cameraOn = true; cameraGeneration = (int)result.Number("generation");
            timer.Start();
            Text("CameraStatus", "Live · on this PC"); Find<System.Windows.Shapes.Ellipse>("CameraDot").Fill = Brush("#65C7A0");
            Text("CaptureFeedback", "Center your face in the ring. The preview is mirrored."); Log("Camera started.");
        }
        private async Task StopCamera()
        {
            epoch++; operation = ""; Ring.Active = false;
            timer.Stop();
            bool wasOn = cameraOn;
            cameraOn = false; ClearPreview();
            if (engine != null) await engine.Send("camera.stop");
            if (wasOn) Log("Camera stopped.");
        }
        private void ClearPreview()
        {
            lock (previewGate) nextPreview = null;
            SetPreview(null);
            Text("CameraStatus", "Camera off"); Find<System.Windows.Shapes.Ellipse>("CameraDot").Fill = Brush("#707986");
        }
        private async Task Suspend()
        {
            Find<PasswordBox>("SignInPassword").Clear();
            if (closed || engine == null) return;
            epoch++; operation = ""; cameraOn = false; timer.Stop(); Ring.Reset(); ClearPreview(); UpdateControls();
            try { await engine.Send("camera.stop"); } catch { }
            if (!closed) { CaptureIdle(); UpdateControls(); }
        }
        private async Task Cancel()
        {
            if (operation == "saving" || operation == "finishing" || busy || closed) return;
            epoch++; operation = ""; Ring.Reset(); Show("SuccessBadge", false);
            if (engine != null) await Run(async delegate { await engine.Send("cancel"); Log("Operation canceled. Simulator locked."); });
            CaptureIdle(); UpdateControls();
        }
        private async Task Navigate(string target)
        {
            if (busy || closed || target == page || operation == "saving" || operation == "finishing") return;
            await Run(async delegate { await StopCamera(); SetPage(target); });
        }
        private void SetPage(string target)
        {
            if (target != "settings") Find<PasswordBox>("SignInPassword").Clear();
            page = target;
            Show("CapturePage", page == "face" || page == "unlock"); Show("LabPage", page == "lab"); Show("ActivityPage", page == "activity"); Show("SettingsPage", page == "settings");
            string[] headings = page == "face" ? new[] { "YOUR FACE, YOUR KEY", "A little more effortless.", "Two gentle circles. A more complete view." }
                : page == "unlock" ? new[] { "LOOK. BLINK. YOU’RE IN.", "Give it a glance.", "Try your face profile in the local unlock simulator." }
                : page == "lab" ? new[] { "THE IMAGE LAB", "Every detail, in focus.", "Repeatable face recognition, one photo at a time." }
                : page == "activity" ? new[] { "SESSION ACTIVITY", "A clear view of things.", "The signals and decisions from this session." }
                : new[] { "PREFERENCES", "Just the way you like it.", "A few thoughtful controls. Everything stays local." };
            Text("PageEyebrow", headings[0]); Text("PageTitle", headings[1]); Text("PageSubtitle", headings[2]);
            foreach (string item in new[] { "Face", "Unlock", "Lab", "Activity", "Settings" })
            {
                var button = Find<Button>("Nav" + item); bool selected = item.ToLowerInvariant() == page;
                button.Background = Brush(selected ? "#344250" : "#00202329"); button.Foreground = Brush(selected ? "#D9EBFF" : "#9AA6B5");
                AutomationProperties.SetHelpText(button, selected ? "Current page" : "Open " + item);
            }
            Find<ScrollViewer>("PageScroll").ScrollToTop(); CaptureIdle(); UpdateControls();
            if (page == "activity") RenderEvents();
            Motion.Enter(Find<StackPanel>("PageContent"));
        }
        private void CaptureIdle()
        {
            Ring.Reset(); Show("SuccessBadge", false);
            Show("PoseList", page == "face" && !HasProfile); Show("UnlockState", page == "unlock");
            Text("CaptureLabel", page == "unlock" ? "UNLOCK SIMULATOR" : "FACE ENROLLMENT");
            Text("GuideKicker", page == "unlock" ? "A FAMILIAR FACE" : HasProfile ? "SAVED ON THIS PC" : "LET’S GET ACQUAINTED");
            Text("GuideTitle", page == "unlock" ? "Ready for a test drive?" : HasProfile ? "Good to see you, " + status.Child("profile").Text("name") + "." : "Your face belongs here.");
            Text("GuideDescription", page == "unlock" ? "Look at the camera, blink when asked, then open both eyes again." : HasProfile ? "Your face profile is ready. Try an unlock or manage your enrollment in Settings." : "Find some even light, sit comfortably, and keep your camera at eye level.");
            Text("CaptureFeedback", "Your camera starts only when you choose. All processing stays on this PC.");
            Text("UnlockLabel", "●  Simulator locked"); Text("UnlockDetail", "Match your face, blink when prompted, then reopen both eyes.");
            PaintPoses(0);
        }
        private async Task Tick()
        {
            if (ticking || busy || closed || !cameraOn || (operation != "enrollment" && operation != "attempt")) return;
            ticking = true; int ticket = epoch; string current = operation; Exception failure = null;
            try
            {
                var result = await engine.Send(current + ".tick");
                if (ticket != epoch || closed) return;
                if (result.Get("observation") != null) ApplyObservation(result.Child("observation"));
                if (current == "enrollment")
                {
                    var enrollment = result.Child("enrollment"); ApplyEnrollment(enrollment);
                    if (enrollment.Text("state") == "expired") throw new InvalidOperationException(enrollment.Text("message"));
                    if (enrollment.Text("state") == "ready")
                    {
                        operation = "saving"; UpdateControls(); Text("CaptureFeedback", "Saving your face profile…");
                        status = await engine.Send("enrollment.finish");
                        if (ticket != epoch || closed) return;
                        UpdateStatus(); EnrollmentSaved();
                        Log("Enrolled " + status.Child("profile").Text("name") + " with " + status.Child("profile").Number("samples") + " circular views.", "success");
                        await engine.Send("camera.stop");
                        if (ticket != epoch || closed) return;
                        operation = ""; cameraOn = false; timer.Stop(); ClearPreview();
                    }
                }
                else
                {
                    var attempt = result.Child("attempt"); ApplyAttempt(attempt);
                    if (attempt.Text("state") != "scanning")
                    {
                        operation = "finishing"; Ring.Active = false; UpdateControls(); Log(attempt.Text("message"), attempt.Text("state") == "unlocked" ? "success" : "info");
                        await engine.Send("camera.stop");
                        if (ticket != epoch || closed) return;
                        operation = ""; cameraOn = false; timer.Stop(); ClearPreview();
                    }
                    else if (result.Flag("prompt_pending"))
                    {
                        // Let WPF present the instruction before discarding pre-prompt samples.
                        await window.Dispatcher.InvokeAsync(delegate { }, DispatcherPriority.ContextIdle);
                        if (ticket == epoch && !closed) await engine.Send("attempt.ack");
                    }
                }
            }
            catch (Exception error)
            {
                if (ticket == epoch && !closed) { operation = ""; Ring.Active = false; failure = error; Fail(error); }
            }
            finally { ticking = false; if (!closed) UpdateControls(); }
            if (failure != null) { try { await StopCamera(); } catch { } }
        }
        private void ApplyEnrollment(Dictionary<string, object> enrollment)
        {
            var guidance = enrollment.Child("guidance"); int captured = (int)enrollment.Number("captured");
            string title = enrollment.Text("title");
            if (Find<TextBlock>("GuideTitle").Text != title) { Text("GuideTitle", title); Motion.Enter(Find<TextBlock>("GuideTitle")); }
            int total = Math.Max(1, (int)enrollment.Number("total"));
            Text("GuideKicker", captured == 0 ? "FIRST, FACE THE CAMERA" : "CIRCLE " + Math.Max(1, (int)enrollment.Number("circuit")) + " OF 2 · VIEW " + Math.Min(total, captured + 1) + " OF " + total);
            Text("GuideDescription", enrollment.Text("instruction")); Text("CaptureFeedback", enrollment.Text("message"));
            Ring.Step = enrollment.Flag("returning") ? "center" : enrollment.Text("step");
            Ring.Set(captured, guidance.Number("yaw"), guidance.Number("pitch"), enrollment.Number("hold_progress"), enrollment.Text("state") == "ready");
            PaintPoses(captured);
        }
        private void PaintPoses(int captured)
        {
            string[] labels = { "Face the camera", "First gentle circle · " + Math.Max(0, Math.Min(8, captured - 1)) + "/8 views", "Return briefly to center", "Second gentle circle · " + Math.Max(0, Math.Min(8, captured - 9)) + "/8 views", "17 views · at least 51 observations" };
            int[] ends = { 1, 9, 10, 17, 17 };
            int stage = captured == 0 ? 0 : captured < 9 ? 1 : Ring.Step == "center" && captured == 9 ? 2 : captured < 17 ? 3 : 4;
            for (int i = 0; i < labels.Length; i++) { var label = Find<TextBlock>("Pose" + i); bool done = captured >= ends[i] && i != stage; label.Text = (done ? "✓   " : i == stage ? "●   " : "○   ") + labels[i]; label.Foreground = Brush(done ? "#77CDB0" : i == stage ? "#D7E9FF" : "#788391"); }
        }
        private void EnrollmentSaved()
        {
            Ring.Active = false; Ring.Step = "center"; Ring.Set(17, 0, 0, 0, true); PaintPoses(17); Show("SuccessBadge", true);
            Text("GuideKicker", "YOU’RE ALL SET"); Text("GuideTitle", "A face to remember.");
            Text("GuideDescription", "Both circles are saved. Head to Unlock test and give it a try.");
            Text("CaptureFeedback", "Enrollment complete. " + status.Text("storage") + " · stored on this PC.");
        }
        private void ApplyAttempt(Dictionary<string, object> attempt)
        {
            string state = attempt.Text("state"), phase = attempt.Text("phase"); bool unlocked = state == "unlocked";
            Text("GuideKicker", unlocked ? "IDENTITY + BLINK VERIFIED" : "LIVE VERIFICATION");
            string title = unlocked ? "Look. You’re in." : state != "scanning" ? "Let’s try that again." : phase == "blink" ? "Now, a natural blink." : phase == "reopen" || phase == "confirm" ? "Open both eyes." : "Looking for you…";
            if (Find<TextBlock>("GuideTitle").Text != title) { Text("GuideTitle", title); Motion.Enter(Find<TextBlock>("GuideTitle")); }
            Text("GuideDescription", attempt.Text("message")); Text("CaptureFeedback", attempt.Text("message"));
            Text("UnlockLabel", unlocked ? "✓  Simulator unlocked" : "●  Simulator locked");
            Text("UnlockDetail", unlocked ? "Face matched. Fresh blink confirmed. Both eyes open." : "The simulator waits for all checks to pass.");
            Ring.Step = "center"; Ring.Set(unlocked ? 17 : 0, 0, 0, attempt.Number("streak") / Math.Max(1, attempt.Number("required")), unlocked);
            Show("SuccessBadge", unlocked);
        }
        private void ApplyObservation(Dictionary<string, object> observation)
        {
            var attention = observation.Child("attention");
            Text("EyeMetric", "Eyes " + attention.Text("eyes") + (attention.Text("eye_method") == "pose-calibrated" ? " · tilt adjusted" : ""));
            Text("InferenceMetric", observation.Number("latency_ms").ToString("F0") + " ms" + (observation.Get("similarity") != null ? " · similarity " + observation.Number("similarity").ToString("F3") : "") + (!observation.Flag("identity_checked") ? " · tracked" : ""));
        }
        private string ObservationSummary(Dictionary<string, object> observation)
        {
            return observation.Text("message") + " · eyes " + observation.Child("attention").Text("eyes") + " · " + observation.Number("latency_ms").ToString("F0") + " ms" + (observation.Get("similarity") == null ? "" : " · similarity " + observation.Number("similarity").ToString("F3"));
        }
        private void UpdateStatus()
        {
            bool loading = status.Child("engine").Flag("loading");
            Text("EngineStatus", Ready ? "On-device · ready" : loading ? "Starting locally…" : "Engine unavailable"); Find<System.Windows.Shapes.Ellipse>("EngineDot").Fill = Brush(Ready ? "#65C7A0" : loading ? "#9AA6B5" : "#E1A179");
            Text("StorageLabel", status.Text("storage") == "Memory only" ? "Memory only · this session" : "Encrypted for your Windows user");
            var profile = status.Child("profile");
            Text("ProfileTitle", profile.Text("name")); Text("ProfileDetail", profile.Number("samples") + " samples · " + status.Text("storage"));
            Text("SettingsProfile", HasProfile ? profile.Text("name") + " · " + profile.Number("samples") + " samples · " + status.Text("storage") + "\n" + profile.Text("matching") + " matching · " + profile.Text("source") + " enrollment" : status.Text("storage_error") != "" ? status.Text("storage_error") : "No face enrolled yet.");
            if (!loading && status.Child("engine").Get("message") != null) Fail(new InvalidOperationException(status.Child("engine").Text("message")));
            if (status.Get("storage_error") != null) Fail(new InvalidOperationException(status.Text("storage_error")));
            UpdateControls();
        }
        private void UpdateControls()
        {
            bool working = operation != "", locked = busy || operation == "saving" || operation == "finishing";
            foreach (var name in new[] { "NavFace", "NavUnlock", "NavLab", "NavActivity", "NavSettings" }) Find<Button>(name).IsEnabled = !locked;
            Show("NameArea", page == "face" && !HasProfile); Show("ProfileSummary", HasProfile || page == "unlock");
            Find<TextBox>("ProfileName").IsReadOnly = working || busy;
            var main = Find<Button>("MainAction");
            main.Content = operation == "saving" ? "Saving…" : operation == "finishing" ? "Finishing…" : operation == "enrollment" ? "Enrolling…" : operation == "attempt" ? "Verifying…" : page == "unlock" ? "Test face unlock  →" : HasProfile ? "Manage profile" : "Begin enrollment  →";
            main.IsEnabled = !busy && !working && (page == "face" && HasProfile || Ready && (page == "unlock" ? HasProfile : Find<TextBox>("ProfileName").Text.Trim().Length > 0 && status.Get("storage_error") == null));
            Find<Button>("CameraButton").Content = cameraOn ? "Stop camera" : "Start camera";
            Find<Button>("CameraButton").IsEnabled = !busy && !working && Ready;
            Find<Button>("InspectFrame").IsEnabled = !busy && !working && Ready && cameraOn;
            Show("CancelAction", working); Find<Button>("CancelAction").IsEnabled = !locked;
            Find<Button>("DeleteProfile").IsEnabled = !busy && (HasProfile || status.Get("storage_error") != null);
            Find<Button>("ChooseImages").IsEnabled = !busy;
            Find<Button>("ClearImages").IsEnabled = !busy && images.Count > 0;
            Find<ComboBox>("ImagePicker").IsEnabled = !busy && images.Count > 0;
            Find<Button>("LabInspect").IsEnabled = Ready && !busy && images.Count > 0;
            Find<Button>("LabReject").IsEnabled = Ready && !busy && HasProfile && images.Count > 0;
            Find<Button>("LabEnroll").IsEnabled = Ready && !busy && !HasProfile && status.Get("storage_error") == null && images.Count > 0 && Find<TextBox>("LabName").Text.Trim().Length > 0;
            Find<TextBox>("LabName").IsEnabled = !busy && !HasProfile;
            Find<Button>("LinkSignIn").IsEnabled = !busy && !working && !ephemeral && !smoke && HasProfile && status.Child("profile").Flag("guided") && status.Child("profile").Text("source") == "camera";
            Find<Button>("UnlinkSignIn").IsEnabled = !busy && !smoke;
            Find<Button>("RefreshSignIn").IsEnabled = !busy && !smoke;
            Find<TextBox>("SignInAccount").IsReadOnly = busy;
            Find<ComboBox>("SignInAccountKind").IsEnabled = !busy;
            Find<PasswordBox>("SignInPassword").IsEnabled = !busy;
            Find<Button>("ExportActivity").IsEnabled = events.Count > 0 && !busy;
            Find<Button>("ClearActivity").IsEnabled = events.Count > 0 && !busy;
        }

        private async Task RefreshCameras()
        {
            var names = await Task.Run((Func<List<string>>)CameraCatalog.List);
            if (closed) return;
            var picker = Find<ComboBox>("CameraPicker"); bool wasInitialized = initialized; initialized = false;
            picker.ItemsSource = names; picker.SelectedIndex = Math.Min(cameraIndex, picker.Items.Count - 1);
            initialized = wasInitialized;
        }
        private void UpdateMotion() { Motion.Reduced = Find<CheckBox>("ReduceMotion").IsChecked == true; if (!Motion.Enabled) Motion.StopAll(); Ring.ReducedMotion = !Motion.Enabled; Ring.UpdateMotion(); }
        private void OnSystemSettings(object sender, PropertyChangedEventArgs args) { if (!closed) window.Dispatcher.BeginInvoke(new Action(UpdateMotion)); }
        private void OnSessionSwitch(object sender, SessionSwitchEventArgs args) { if (args.Reason == SessionSwitchReason.SessionLock && !closed) window.Dispatcher.BeginInvoke(new Action(async delegate { await Suspend(); })); }
        private void OnPowerModeChanged(object sender, PowerModeChangedEventArgs args)
        {
            if (!closed && (args.Mode == PowerModes.Suspend || args.Mode == PowerModes.Resume))
                window.Dispatcher.BeginInvoke(new Action(async delegate { await Suspend(); }));
        }
        private void SavePreferences()
        {
            if (smoke) return;
            try { Directory.CreateDirectory(Path.GetDirectoryName(PreferencesPath)); File.WriteAllText(PreferencesPath, Json.Encode(Json.Data("threshold", Find<Slider>("Threshold").Value, "reduce_motion", Find<CheckBox>("ReduceMotion").IsChecked == true, "camera_index", cameraIndex))); }
            catch (IOException error) { Fail(error); }
            catch (UnauthorizedAccessException error) { Fail(error); }
        }
        private static BitmapSource DecodeBitmap(byte[] bytes, int width)
        {
            using (var stream = new MemoryStream(bytes))
            {
                var bitmap = new BitmapImage(); bitmap.BeginInit(); bitmap.CacheOption = BitmapCacheOption.OnLoad; bitmap.StreamSource = stream; bitmap.DecodePixelWidth = width; bitmap.EndInit(); bitmap.Freeze(); return bitmap;
            }
        }
        private async Task ChooseImages()
        {
            var dialog = new OpenFileDialog { Filter = "Face photos|*.jpg;*.jpeg;*.png", Multiselect = true };
            if (dialog.ShowDialog(window) != true) return;
            if (dialog.FileNames.Length > 5) throw new InvalidOperationException("Choose up to five photos of the same person.");
            var loaded = new List<string>(); var previews = new List<BitmapSource>();
            foreach (string path in dialog.FileNames)
            {
                if (new FileInfo(path).Length > 25000000) throw new InvalidOperationException("Choose photos smaller than 25 MB.");
                byte[] bytes = await Task.Run(delegate { return File.ReadAllBytes(path); });
                var image = DecodeBitmap(bytes, 960);
                if (image.PixelWidth < 80 || image.PixelHeight < 80 || image.PixelHeight > 4096) throw new InvalidOperationException("Choose an image with both dimensions between 80 and 4096 pixels after resizing.");
                using (var output = new MemoryStream()) { var encoder = new JpegBitmapEncoder { QualityLevel = 90 }; encoder.Frames.Add(BitmapFrame.Create(image)); encoder.Save(output); loaded.Add("data:image/jpeg;base64," + Convert.ToBase64String(output.ToArray())); }
                previews.Add(image);
            }
            ClearImages(); images.AddRange(loaded); imagePreviews.AddRange(previews);
            var picker = Find<ComboBox>("ImagePicker"); picker.ItemsSource = dialog.FileNames.Select(Path.GetFileName).ToArray(); picker.SelectedIndex = 0;
            Log(images.Count + " photos loaded into memory.");
        }
        private string SelectedImage() { int index = Find<ComboBox>("ImagePicker").SelectedIndex; if (index < 0 || index >= images.Count) throw new InvalidOperationException("Choose a photo first."); return images[index]; }
        private void ClearImages() { Find<ComboBox>("ImagePicker").ItemsSource = null; Find<Image>("LabPreview").Source = null; images.Clear(); imagePreviews.Clear(); Text("LabResult", "Choose an image to inspect face quality, eye state, and similarity."); }
        private void Log(string message, string kind = "info")
        {
            events.Insert(0, Json.Data("time", DateTime.UtcNow.ToString("o"), "message", message, "kind", kind));
            if (events.Count > 100) events.RemoveAt(events.Count - 1);
            if (page == "activity") RenderEvents();
        }
        private void RenderEvents()
        {
            var panel = Find<StackPanel>("EventList"); panel.Children.Clear(); Show("EmptyActivity", events.Count == 0);
            foreach (var entry in events)
            {
                var row = new Grid { Margin = new Thickness(0, 0, 0, 12) }; row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(80) });
                var text = new TextBlock { Text = (entry.Text("kind") == "success" ? "✓  " : "·  ") + entry.Text("message"), TextWrapping = TextWrapping.Wrap, Foreground = Brush(entry.Text("kind") == "error" ? "#EFADB4" : "#C2CBD7"), Margin = new Thickness(0, 0, 18, 0) };
                var time = new TextBlock { Text = DateTime.Parse(entry.Text("time"), CultureInfo.InvariantCulture).ToLocalTime().ToString("HH:mm:ss"), Foreground = Brush("#7E8B9C"), FontSize = 11, HorizontalAlignment = HorizontalAlignment.Right };
                Grid.SetColumn(time, 1); row.Children.Add(text); row.Children.Add(time); panel.Children.Add(row);
            }
            UpdateControls();
        }

        private async Task SmokeTest()
        {
#if VISO_TESTS
            try
            {
                if (!Ready) throw new InvalidOperationException("Real recognition models did not initialize.");
                if (Find<Border>("Notice").Visibility == Visibility.Visible) throw new InvalidOperationException("Model loading left an error notice after successful initialization.");
                string output = Path.Combine(root, "test-results", "native"); Directory.CreateDirectory(output);
                SetPage("face");
                await RenderingChecks.Run(window, output, SetPreview, delegate(bool enrolling) { operation = enrolling ? "enrollment" : ""; UpdateControls(); });
                foreach (string target in new[] { "face", "unlock", "lab", "activity", "settings" })
                {
                    SetPage(target); await Task.Delay(450); Snapshot(Path.Combine(output, target + ".png"));
                }
                SetPage("face");
                string fixture = Path.Combine(root, "tests", ".fixtures", "obama.jpg");
                bool testedPortrait = File.Exists(fixture);
                if (testedPortrait) SetPreview(DecodeBitmap(File.ReadAllBytes(fixture), 720));
                Find<TextBox>("ProfileName").Text = "Native preview";
                operation = "enrollment"; UpdateControls();
                ApplyEnrollment(Json.Data("title", "Continue left and slightly up", "instruction", "Move gently around the circle. Keep both eyes visible.", "message", "That's enough. Pause briefly…", "captured", 2, "total", 17, "circuit", 1, "step", "up_left", "hold_progress", .65, "state", "capturing", "guidance", Json.Data("yaw", 10, "pitch", -7)));
                Ring.Active = true; await Task.Delay(450); Snapshot(Path.Combine(output, "enrollment.png"));
                ApplyEnrollment(Json.Data("title", "Continue slightly up and right", "instruction", "Make the second gentle circle. Blue sectors turn green.", "message", "View captured. Continue gently around the circle.", "captured", 12, "total", 17, "circuit", 2, "step", "up_right", "hold_progress", .45, "state", "capturing", "guidance", Json.Data("yaw", -10, "pitch", -7)));
                await Task.Delay(450); Snapshot(Path.Combine(output, "enrollment-second.png"));
                // Simulate power interruption without touching the physical
                // camera: the real handler must revoke the operation/readout.
                int beforeSuspend = epoch; cameraOn = true; timer.Start();
                Find<PasswordBox>("SignInPassword").Password = "Synthetic only";
                await Suspend();
                if (epoch <= beforeSuspend || cameraOn || timer.IsEnabled || operation != "" || Ring.Active || Find<ImageBrush>("CameraPreview").ImageSource != null || Find<PasswordBox>("SignInPassword").Password != "")
                    throw new InvalidOperationException("Power interruption retained camera, preview, timer, operation or account input.");
                operation = ""; SetPreview(null); Find<TextBox>("ProfileName").Clear(); UpdateControls();
                Find<CheckBox>("ReduceMotion").IsChecked = true;
                EnrollmentSaved(); await Task.Delay(30);
                if ((double)Ring.GetValue(EnrollmentRing.CompleteProperty) != 1) throw new InvalidOperationException("Reduced motion did not resolve immediately.");
                Snapshot(Path.Combine(output, "complete-reduced.png"));
                window.Width = 780; window.Height = 680; SetPage("settings"); await Task.Delay(100); Snapshot(Path.Combine(output, "settings-small.png"));
                SetPage("face"); await Task.Delay(100); Snapshot(Path.Combine(output, "face-small.png"));
                Find<TextBox>("ProfileName").Text = "Native test";
                if (!Find<Button>("MainAction").IsEnabled) throw new InvalidOperationException("Enrollment should be available with an initialized engine and name.");
                SetPage("unlock");
                if (Find<Button>("MainAction").IsEnabled) throw new InvalidOperationException("Unlock must remain disabled without a profile.");
                var blank = new RenderTargetBitmap(100, 100, 96, 96, PixelFormats.Pbgra32); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(blank));
                using (var buffer = new MemoryStream()) {
                    encoder.Save(buffer); var analyzed = await engine.Send("analyze", Json.Data("image", "data:image/png;base64," + Convert.ToBase64String(buffer.ToArray())));
                    if (analyzed.Number("face_count") != 0) throw new InvalidOperationException("Blank input should contain no face.");
                }
                if (testedPortrait)
                {
                    string image;
                    using (var buffer = new MemoryStream()) {
                        var photoEncoder = new JpegBitmapEncoder { QualityLevel = 90 }; photoEncoder.Frames.Add(BitmapFrame.Create(DecodeBitmap(File.ReadAllBytes(fixture), 960))); photoEncoder.Save(buffer);
                        image = "data:image/jpeg;base64," + Convert.ToBase64String(buffer.ToArray());
                    }
                    const string name = "Zoë 李 — Native smoke";
                    var enrolled = await engine.Send("image.enroll", Json.Data("name", name, "images", new[] { image }));
                    if (enrolled.Child("profile").Text("name") != name) throw new InvalidOperationException("Unicode profile names did not survive native IPC.");
                    status = enrolled; UpdateStatus();
                    if (!Find<Button>("MainAction").IsEnabled) throw new InvalidOperationException("Unlock should be enabled after enrollment.");
                    var rejected = await engine.Send("image.test", Json.Data("image", image, "threshold", .35));
                    if (rejected.Child("attempt").Text("state") == "unlocked" || rejected.Child("observation").Number("similarity") < .9) throw new InvalidOperationException("Matching still image must be recognized but cannot unlock.");
                    status = await engine.Send("profile.delete"); UpdateStatus();
                    if (HasProfile) throw new InvalidOperationException("Profile deletion failed.");
                }
                await engine.Send("cancel"); await engine.Send("camera.stop");
                File.WriteAllText(Path.Combine(output, "smoke.json"), Json.Encode(Json.Data("passed", true, "engine", status.Child("engine"), "real_portrait_enrollment_rejection_deletion", testedPortrait, "checks", new[] { "real worker initialization", "preview coverage, crop and mirroring", "profile name visibility and edit state", "five native pages", "two-pass circular enrollment visual state", "eight-sector blue/green progress", "cached frozen ring resources", "reduced motion completion", "power interruption cleanup", "minimum window size", "control gating", "real blank-frame inference", "Unicode IPC", "cancel and camera stop" })));
                window.Close();
            }
            catch (Exception error) { SmokeFail(error); }
#else
            await Task.FromResult(0);
            SmokeFail(new InvalidOperationException("Build the test branch with -SmokeTest to run native checks."));
#endif
        }
        private void Snapshot(string path)
        {
            window.UpdateLayout(); var visual = (FrameworkElement)window.Content;
            var bitmap = new RenderTargetBitmap((int)visual.ActualWidth, (int)visual.ActualHeight, 96, 96, PixelFormats.Pbgra32); bitmap.Render(visual);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap)); using (var file = File.Create(path)) encoder.Save(file);
        }
        private void SmokeFail(Exception error) { ExitCode = 1; string output = Path.Combine(root, "test-results", "native"); Directory.CreateDirectory(output); File.WriteAllText(Path.Combine(output, "error.txt"), error.ToString()); window.Close(); }
        private void Close()
        {
            Find<PasswordBox>("SignInPassword").Clear();
            closed = true; epoch++; timer.Stop(); Ring.Active = false; Motion.StopAll();
            SystemParameters.StaticPropertyChanged -= OnSystemSettings; SystemEvents.SessionSwitch -= OnSessionSwitch; SystemEvents.PowerModeChanged -= OnPowerModeChanged;
            if (engine != null) { engine.Event -= EngineEvent; engine.Dispose(); }
            ClearImages(); lock (previewGate) nextPreview = null;
        }
    }
}
