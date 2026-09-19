using System;
using System.IO;
using System.Text.Json;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Edge 在线语音识别宿主
// 通信协议：stdout 输出 JSON 行（结果/错误/状态），stdin 接收 JSON 命令（一行一个）。
// 由 VRChat OSC Chatbox 的 Python 侧用 subprocess 启动，CREATE_NO_WINDOW 下无窗口。
class SpeechHost : Form
{
    WebView2 wv;
    volatile bool exiting = false;
    string currentLang = "zh-CN";
    bool startOnReady = false;

    const string HTML = @"<!doctype html><html><body>
<script>
var rec = null;
var autoRestart = true;

function emit(obj){ try { window.chrome.webview.postMessage(JSON.stringify(obj)); } catch(e){} }

function startRec(lang){
  stopRec();
  try {
    rec = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
  } catch(e) {
    emit({type:'error', code:'unsupported', msg:String(e)});
    return;
  }
  rec.lang = lang || 'zh-CN';
  rec.continuous = false;
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = function(e){
    var t = '';
    for (var i = e.resultIndex; i < e.results.length; i++){
      if (e.results[i].isFinal) { t += e.results[i][0].transcript; }
    }
    if (t.trim()) { emit({type:'result', text:t.trim()}); }
  };
  rec.onerror = function(e){
    emit({type:'error', code:(e.error || 'unknown')});
    rec = null;
  };
  rec.onend = function(){
    rec = null;
    emit({type:'end'});
    if (autoRestart) { setTimeout(function(){ startRec(lang); }, 150); }
  };
  try { rec.start(); emit({type:'listening', lang:lang}); }
  catch(e){ rec = null; emit({type:'error', code:'start', msg:String(e)}); }
}

function stopRec(){
  var r = rec; rec = null;
  if (r) { r.onend = null; try{ r.stop(); }catch(e){} }
}
function setAutoRestart(v){ autoRestart = !!v; }
</script>
</body></html>";

    [STAThread]
    static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new SpeechHost());
    }

    SpeechHost()
    {
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        Opacity = 0.0;
        Width = 200;
        Height = 200;
        StartPosition = FormStartPosition.Manual;
        Location = new System.Drawing.Point(-5000, -5000);

        wv = new WebView2 { Dock = DockStyle.Fill };
        Controls.Add(wv);

        wv.CoreWebView2InitializationCompleted += OnInit;
        _ = InitWebViewAsync();

        var t = new Thread(ReadStdinLoop) { IsBackground = true };
        t.Start();
    }

    async System.Threading.Tasks.Task InitWebViewAsync()
    {
        try
        {
            string args = "--use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required";
            var proxy = DetectProxy();
            if (!string.IsNullOrEmpty(proxy))
                args += " --proxy-server=\"" + proxy + "\"";
            var opts = new CoreWebView2EnvironmentOptions(args);
            var env = await CoreWebView2Environment.CreateAsync(null, null, opts);
            await wv.EnsureCoreWebView2Async(env);
        }
        catch (Exception ex)
        {
            Emit(new { type = "error", code = "init", msg = ex.Message });
            exiting = true;
            Application.Exit();
        }
    }

    // Web Speech 在 WebView2 里走云端识别服务，国内直连会 network 错误，
    // 自动探测本地代理并让 WebView2 走代理。
    static string DetectProxy()
    {
        try
        {
            var env = Environment.GetEnvironmentVariable("EDGE_SPEECH_PROXY");
            if (!string.IsNullOrWhiteSpace(env)) return env.Trim();
        }
        catch { }
        try
        {
            using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Internet Settings"))
            {
                if (key != null)
                {
                    var enable = key.GetValue("ProxyEnable");
                    var server = key.GetValue("ProxyServer") as string;
                    if (Convert.ToInt32(enable ?? 0) == 1 && !string.IsNullOrWhiteSpace(server))
                    {
                        var s = server.Trim();
                        if (s.Contains("="))
                        {
                            foreach (var part in s.Split(';'))
                            {
                                if (part.StartsWith("https=", StringComparison.OrdinalIgnoreCase) ||
                                    part.StartsWith("http=", StringComparison.OrdinalIgnoreCase))
                                {
                                    s = part.Split(new[] { '=' }, 2)[1];
                                    break;
                                }
                            }
                        }
                        if (!s.StartsWith("http")) s = "http://" + s;
                        return s;
                    }
                }
            }
        }
        catch { }
        foreach (var cand in new[]
        {
            "socks5://127.0.0.1:10808", "socks5://127.0.0.1:1080",
            "http://127.0.0.1:10809", "http://127.0.0.1:7890"
        })
        {
            try
            {
                var uri = new Uri(cand);
                using (var c = new System.Net.Sockets.TcpClient())
                {
                    var task = c.ConnectAsync(uri.Host, uri.Port);
                    if (task.Wait(250) && c.Connected) return cand;
                }
            }
            catch { }
        }
        return null;
    }

    void OnInit(object sender, CoreWebView2InitializationCompletedEventArgs e)
    {
        if (e.IsSuccess)
        {
            var core = wv.CoreWebView2;
            core.PermissionRequested += (s, pe) => pe.State = CoreWebView2PermissionState.Allow;
            core.WebMessageReceived += OnWebMessage;
            core.NavigateToString(HTML);
            Emit(new { type = "started" });
            if (startOnReady)
            {
                startOnReady = false;
                StartRec();
            }
        }
        else
        {
            Emit(new { type = "error", code = "init", msg = e.InitializationException?.Message });
            exiting = true;
            Application.Exit();
        }
    }

    void OnWebMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        var raw = e.WebMessageAsJson;
        // JS 侧 postMessage(JSON.stringify(obj))，WebMessageAsJson 会把它再编码为带引号的 JSON 字符串，这里解一层
        try
        {
            using var doc = JsonDocument.Parse(raw);
            if (doc.RootElement.ValueKind == JsonValueKind.String)
                raw = doc.RootElement.GetString() ?? raw;
        }
        catch { /* 解不开就原样输出 */ }
        Console.WriteLine(raw);
        Console.Out.Flush();
    }

    void ReadStdinLoop()
    {
        var input = Console.In;
        string line;
        while (!exiting && (line = input.ReadLine()) != null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            HandleCommand(line);
        }
        if (!exiting)
        {
            exiting = true;
            Application.Exit();
        }
    }

    void HandleCommand(string line)
    {
        try
        {
            using var doc = JsonDocument.Parse(line);
            var root = doc.RootElement;
            var cmd = root.GetProperty("cmd").GetString();
            switch (cmd)
            {
                case "start":
                    if (root.TryGetProperty("lang", out var l) && !string.IsNullOrEmpty(l.GetString()))
                        currentLang = l.GetString();
                    StartRec();
                    break;
                case "stop":
                    StopRec();
                    break;
                case "set_lang":
                    if (root.TryGetProperty("lang", out var l2) && !string.IsNullOrEmpty(l2.GetString()))
                        currentLang = l2.GetString();
                    RunOnUI(() => wv.CoreWebView2?.ExecuteScriptAsync(
                        "setAutoRestart(true); startRec('" + Esc(currentLang) + "')"));
                    break;
                case "pause":
                    RunOnUI(() => wv.CoreWebView2?.ExecuteScriptAsync("setAutoRestart(false); stopRec()"));
                    break;
                case "resume":
                    RunOnUI(() => wv.CoreWebView2?.ExecuteScriptAsync("setAutoRestart(true); startRec('" + Esc(currentLang) + "')"));
                    break;
                case "exit":
                    RunOnUI(() => wv.CoreWebView2?.ExecuteScriptAsync("stopRec()"));
                    exiting = true;
                    Application.Exit();
                    break;
            }
        }
        catch (Exception ex)
        {
            Emit(new { type = "error", code = "cmd", msg = ex.Message });
        }
    }

    void StartRec()
    {
        RunOnUI(() =>
        {
            if (wv.CoreWebView2 == null)
            {
                startOnReady = true;
                return;
            }
            wv.CoreWebView2.ExecuteScriptAsync("setAutoRestart(true); startRec('" + Esc(currentLang) + "')");
        });
    }

    void StopRec()
    {
        RunOnUI(() => wv.CoreWebView2?.ExecuteScriptAsync("stopRec()"));
    }

    void RunOnUI(Action act)
    {
        if (InvokeRequired)
        {
            try { BeginInvoke(act); } catch { }
        }
        else act();
    }

    static void Emit(object obj)
    {
        Console.WriteLine(JsonSerializer.Serialize(obj));
        Console.Out.Flush();
    }

    static string Esc(string s) => (s ?? "").Replace("\\", "\\\\").Replace("'", "\\'");
}
