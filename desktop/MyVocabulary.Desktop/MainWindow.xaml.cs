using Microsoft.Web.WebView2.Core;
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace MyVocabulary.Desktop;

public partial class MainWindow : Window
{
    private static readonly TimeSpan MinimumSplashDuration = TimeSpan.FromMilliseconds(1350);
    private static readonly string[] LoadingPhrases =
    {
        "整理今天的学习进度",
        "唤醒熟悉的单词朋友",
        "翻开你的词汇本",
    };

    private readonly CancellationTokenSource lifetime = new();
    private readonly Stopwatch startupClock = Stopwatch.StartNew();
    private readonly bool animationsEnabled = SystemParameters.ClientAreaAnimation && !SystemParameters.HighContrast;
    private string? projectRoot;
    private bool splashVisible = true;
    private bool navigationHandled;

    public MainWindow()
    {
        InitializeComponent();
        WebView.DefaultBackgroundColor = System.Drawing.Color.FromArgb(255, 247, 251, 244);
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        startupClock.Restart();
        StartSplashMotion();

        try
        {
            projectRoot = ProjectLocator.FindRoot();
            StatusText.Text = "正在检查本地学习服务…";
            await BackendHost.EnsureRunningAsync(projectRoot, lifetime.Token);

            StatusText.Text = "正在打开今天的学习界面…";
            var userDataFolder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "MyVocabulary",
                "WebView2");
            Directory.CreateDirectory(userDataFolder);
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: userDataFolder);
            await WebView.EnsureCoreWebView2Async(environment);
            WebView.CoreWebView2.Settings.IsStatusBarEnabled = false;
            WebView.CoreWebView2.NavigationCompleted += WebView_NavigationCompleted;
            WebView.Source = new Uri(BackendHost.AppUrl);
            _ = KeepBackendAliveAsync(lifetime.Token);
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception error)
        {
            splashVisible = false;
            SetPhraseInstant("这次没有打开成功");
            StatusText.Text = "启动失败：" + error.Message;
            MessageBox.Show(this, error.Message, "我的词汇本启动失败", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void StartSplashMotion()
    {
        if (!animationsEnabled)
        {
            LogoScale.ScaleX = 1;
            LogoScale.ScaleY = 1;
            LogoTranslate.Y = 0;
            LogoHaloScale.ScaleX = 1;
            LogoHaloScale.ScaleY = 1;
            DotOne.Opacity = DotTwo.Opacity = DotThree.Opacity = 0.65;
            SetPhraseInstant(LoadingPhrases[0]);
            return;
        }

        var settleEase = new BackEase { Amplitude = 0.24, EasingMode = EasingMode.EaseOut };
        LogoScale.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.84, 1, TimeSpan.FromMilliseconds(390)) { EasingFunction = settleEase });
        LogoScale.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.84, 1, TimeSpan.FromMilliseconds(390)) { EasingFunction = settleEase });
        var logoSettle = new DoubleAnimation(12, 0, TimeSpan.FromMilliseconds(390)) { EasingFunction = settleEase };
        logoSettle.Completed += (_, _) =>
        {
            if (!splashVisible) return;
            LogoTranslate.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(0, -4, TimeSpan.FromMilliseconds(1500))
            {
                AutoReverse = true,
                RepeatBehavior = RepeatBehavior.Forever,
                EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
            });
        };
        LogoTranslate.BeginAnimation(TranslateTransform.YProperty, logoSettle);

        LogoHaloScale.BeginAnimation(ScaleTransform.ScaleXProperty, PulseAnimation(0.92, 1.05, 1250));
        LogoHaloScale.BeginAnimation(ScaleTransform.ScaleYProperty, PulseAnimation(0.92, 1.05, 1250));
        BeginDotPulse(DotOne, 0);
        BeginDotPulse(DotTwo, 160);
        BeginDotPulse(DotThree, 320);
        TopBlobTranslate.BeginAnimation(TranslateTransform.XProperty, DriftAnimation(0, 18, 4800));
        BottomBlobTranslate.BeginAnimation(TranslateTransform.YProperty, DriftAnimation(0, -14, 4300));

        _ = RotateLoadingPhrasesAsync(lifetime.Token);
    }

    private static DoubleAnimation PulseAnimation(double from, double to, int milliseconds)
    {
        return new DoubleAnimation(from, to, TimeSpan.FromMilliseconds(milliseconds))
        {
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
    }

    private static DoubleAnimation DriftAnimation(double from, double to, int milliseconds)
    {
        return new DoubleAnimation(from, to, TimeSpan.FromMilliseconds(milliseconds))
        {
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
    }

    private static void BeginDotPulse(System.Windows.Shapes.Ellipse dot, int delayMilliseconds)
    {
        dot.BeginAnimation(OpacityProperty, new DoubleAnimation(0.28, 1, TimeSpan.FromMilliseconds(410))
        {
            BeginTime = TimeSpan.FromMilliseconds(delayMilliseconds),
            AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever,
            EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        });
    }

    private async Task RotateLoadingPhrasesAsync(CancellationToken cancellationToken)
    {
        try
        {
            var phraseIndex = 0;
            while (splashVisible && !cancellationToken.IsCancellationRequested)
            {
                await AnimatePhraseAsync(LoadingPhrases[phraseIndex], cancellationToken);
                phraseIndex = (phraseIndex + 1) % LoadingPhrases.Length;
                await Task.Delay(620, cancellationToken);
            }
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task AnimatePhraseAsync(string phrase, CancellationToken cancellationToken)
    {
        foreach (UIElement element in RotatingPhrasePanel.Children)
        {
            element.BeginAnimation(OpacityProperty, new DoubleAnimation(0, TimeSpan.FromMilliseconds(105)));
            if (element.RenderTransform is TranslateTransform translate)
            {
                translate.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(-8, TimeSpan.FromMilliseconds(105)));
            }
        }

        if (RotatingPhrasePanel.Children.Count > 0)
        {
            await Task.Delay(115, cancellationToken);
        }

        RotatingPhrasePanel.Children.Clear();
        AutomationProperties.SetName(RotatingPhrasePanel, phrase);
        var enterEase = new BackEase { Amplitude = 0.18, EasingMode = EasingMode.EaseOut };

        for (var index = 0; index < phrase.Length; index++)
        {
            var character = new TextBlock
            {
                Text = phrase[index] == ' ' ? "\u00A0" : phrase[index].ToString(),
                FontFamily = new FontFamily("Segoe UI Variable Display, Segoe UI, Microsoft YaHei UI"),
                FontSize = 21,
                FontWeight = FontWeights.SemiBold,
                Foreground = new SolidColorBrush(Color.FromRgb(47, 58, 64)),
                Opacity = 0,
                RenderTransform = new TranslateTransform(0, 15),
            };
            RotatingPhrasePanel.Children.Add(character);

            var delay = TimeSpan.FromMilliseconds(index * 24);
            character.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(210))
            {
                BeginTime = delay,
                EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut },
            });
            ((TranslateTransform)character.RenderTransform).BeginAnimation(
                TranslateTransform.YProperty,
                new DoubleAnimation(15, 0, TimeSpan.FromMilliseconds(285))
                {
                    BeginTime = delay,
                    EasingFunction = enterEase,
                });
        }

        await Task.Delay(285 + Math.Max(0, phrase.Length - 1) * 24, cancellationToken);
    }

    private void SetPhraseInstant(string phrase)
    {
        RotatingPhrasePanel.Children.Clear();
        AutomationProperties.SetName(RotatingPhrasePanel, phrase);
        RotatingPhrasePanel.Children.Add(new TextBlock
        {
            Text = phrase,
            FontFamily = new FontFamily("Segoe UI Variable Display, Segoe UI, Microsoft YaHei UI"),
            FontSize = 21,
            FontWeight = FontWeights.SemiBold,
            Foreground = new SolidColorBrush(Color.FromRgb(47, 58, 64)),
        });
    }

    private async void WebView_NavigationCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        if (e.IsSuccess && !navigationHandled)
        {
            navigationHandled = true;
            StatusText.Text = "准备好了，开始今天的学习吧";

            try
            {
                var remaining = MinimumSplashDuration - startupClock.Elapsed;
                if (remaining > TimeSpan.Zero)
                {
                    await Task.Delay(remaining, lifetime.Token);
                }
                await HideLoadingOverlayAsync(lifetime.Token);
            }
            catch (OperationCanceledException)
            {
            }
            return;
        }

        if (!e.IsSuccess)
        {
            splashVisible = false;
            SetPhraseInstant("界面暂时没有打开");
            StatusText.Text = $"界面加载失败：{e.WebErrorStatus}";
        }
    }

    private async Task HideLoadingOverlayAsync(CancellationToken cancellationToken)
    {
        splashVisible = false;
        if (!animationsEnabled)
        {
            LoadingOverlay.Visibility = Visibility.Collapsed;
            WebView.Visibility = Visibility.Visible;
            return;
        }

        var contentFade = new DoubleAnimation(0, TimeSpan.FromMilliseconds(170))
        {
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseIn },
        };
        LoadingContent.BeginAnimation(OpacityProperty, contentFade);
        LoadingContentTranslate.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(0, -8, TimeSpan.FromMilliseconds(190))
        {
            EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseIn },
        });

        await Task.Delay(180, cancellationToken);
        LoadingOverlay.Visibility = Visibility.Collapsed;
        WebView.Visibility = Visibility.Visible;
    }

    private async Task KeepBackendAliveAsync(CancellationToken cancellationToken)
    {
        if (projectRoot is null) return;
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(30));
        while (await timer.WaitForNextTickAsync(cancellationToken))
        {
            var restarted = await BackendHost.EnsureRunningAsync(projectRoot, cancellationToken);
            if (restarted)
            {
                await Dispatcher.InvokeAsync(() => WebView.Reload());
            }
        }
    }

    private void Window_Closed(object? sender, EventArgs e)
    {
        splashVisible = false;
        lifetime.Cancel();
        WebView.Dispose();
        lifetime.Dispose();
    }
}
