using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace MyVocabulary.Desktop;

internal static class BackendHost
{
    public const string AppUrl = "http://127.0.0.1:8766/";
    private const string HealthUrl = "http://127.0.0.1:8766/api/health";
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(2) };

    public static async Task<bool> EnsureRunningAsync(string projectRoot, CancellationToken cancellationToken)
    {
        if (await IsHealthyAsync(cancellationToken)) return false;

        await StopIncompatibleServiceAsync(projectRoot, cancellationToken);

        var pythonw = FindPythonWindowed();
        if (pythonw is null)
        {
            throw new InvalidOperationException("未找到 pythonw.exe。请先安装 Python 3，或修复当前 Python 命令。 ");
        }

        var startScript = Path.Combine(projectRoot, "start.py");
        var processInfo = new ProcessStartInfo
        {
            FileName = pythonw,
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        processInfo.ArgumentList.Add(startScript);
        processInfo.ArgumentList.Add("--host");
        processInfo.ArgumentList.Add("127.0.0.1");
        processInfo.ArgumentList.Add("--port");
        processInfo.ArgumentList.Add("8766");
        processInfo.ArgumentList.Add("--no-browser");
        processInfo.ArgumentList.Add("--idle-timeout");
        processInfo.ArgumentList.Add("180");
        Process.Start(processInfo);

        var deadline = DateTime.UtcNow.AddSeconds(12);
        while (DateTime.UtcNow < deadline)
        {
            await Task.Delay(250, cancellationToken);
            if (await IsHealthyAsync(cancellationToken)) return true;
        }

        throw new InvalidOperationException("本地学习服务未能在 12 秒内启动。请确认端口 8766 未被其他程序占用。");
    }

    private static async Task<bool> IsHealthyAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await Http.GetAsync(HealthUrl, cancellationToken);
            if (!response.IsSuccessStatusCode) return false;
            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
            using var payload = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
            var root = payload.RootElement;
            return root.TryGetProperty("ok", out var ok) && ok.GetBoolean()
                && root.TryGetProperty("app", out var app) && app.GetString() == "my-vocabulary"
                && root.TryGetProperty("api_version", out var version) && version.GetInt32() == 4;
        }
        catch (HttpRequestException)
        {
            return false;
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return false;
        }
    }

    private static async Task StopIncompatibleServiceAsync(string projectRoot, CancellationToken cancellationToken)
    {
        var script = Path.Combine(projectRoot, "scripts", "stop_stale_backend.ps1");
        var startScript = Path.Combine(projectRoot, "start.py");
        if (!File.Exists(script))
        {
            throw new FileNotFoundException("找不到旧服务清理脚本。", script);
        }

        var processInfo = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        processInfo.ArgumentList.Add("-NoProfile");
        processInfo.ArgumentList.Add("-NonInteractive");
        processInfo.ArgumentList.Add("-ExecutionPolicy");
        processInfo.ArgumentList.Add("Bypass");
        processInfo.ArgumentList.Add("-File");
        processInfo.ArgumentList.Add(script);
        processInfo.ArgumentList.Add("-StartScript");
        processInfo.ArgumentList.Add(startScript);

        using var process = Process.Start(processInfo)
            ?? throw new InvalidOperationException("无法检查旧版学习服务。");
        await process.WaitForExitAsync(cancellationToken);
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException("端口 8766 被其他程序占用，未停止该程序。");
        }
    }

    private static string? FindPythonWindowed()
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        foreach (var directory in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim('"'), "pythonw.exe");
                if (File.Exists(candidate)) return candidate;
            }
            catch
            {
            }
        }
        return null;
    }
}

internal static class ProjectLocator
{
    public static string FindRoot()
    {
        foreach (var startingPath in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
        {
            var directory = new DirectoryInfo(Path.GetFullPath(startingPath));
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "start.py"))
                    && File.Exists(Path.Combine(directory.FullName, "app", "index.html")))
                {
                    return directory.FullName;
                }
                directory = directory.Parent;
            }
        }

        throw new DirectoryNotFoundException("找不到英语学习工具项目目录；请从项目内的快捷方式启动。");
    }
}
