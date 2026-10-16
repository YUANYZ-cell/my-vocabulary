using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows;

namespace MyVocabulary.Desktop;

public partial class App : Application
{
    private Mutex? instanceMutex;

    protected override void OnStartup(StartupEventArgs e)
    {
        instanceMutex = new Mutex(true, @"Local\MyVocabularyDesktop-v1", out var isFirstInstance);
        if (!isFirstInstance)
        {
            NativeWindowActivator.ActivateExisting();
            Shutdown();
            return;
        }

        base.OnStartup(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        if (instanceMutex is not null)
        {
            instanceMutex.ReleaseMutex();
            instanceMutex.Dispose();
        }
        base.OnExit(e);
    }
}

internal static class NativeWindowActivator
{
    private delegate bool EnumWindowsCallback(IntPtr window, IntPtr data);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr data);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr window, StringBuilder text, int count);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr window, int command);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);

    public static void ActivateExisting()
    {
        EnumWindows((window, _) =>
        {
            if (!IsWindowVisible(window)) return true;
            var title = new StringBuilder(256);
            GetWindowText(window, title, title.Capacity);
            if (!title.ToString().StartsWith("My Vocabulary / 我的词汇本", StringComparison.Ordinal)) return true;

            GetWindowThreadProcessId(window, out var processId);
            try
            {
                if (!string.Equals(Process.GetProcessById((int)processId).ProcessName, "MyVocabulary", StringComparison.OrdinalIgnoreCase)) return true;
            }
            catch
            {
                return true;
            }

            if (IsIconic(window)) ShowWindowAsync(window, 9);
            SetForegroundWindow(window);
            return false;
        }, IntPtr.Zero);
    }
}
