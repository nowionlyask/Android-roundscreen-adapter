package com.biliauto.watch;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.util.TypedValue;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import android.util.Log;

/**
 * BiliRemote 手表审批客户端。
 *
 * 一个 WebView 壳：加载 Pi 上的 /watch 页面。
 * 自带失败兜底：连不上时显示原因 + 重试按钮，不会白屏。
 */
public class MainActivity extends Activity {

    // ======== 配置 ========
    private static final String BASE_URL = "https://[YOUR_SERVER_IPV6]:8788";
    private static final String TOKEN = "YOUR_WATCH_TOKEN";
    // 配对密钥，用于给 Pi 的接口签名
    private static final String KEY = "YOUR_PAIRING_KEY";
    private static final String PAGE = BASE_URL + "/watch?t=" + TOKEN;

    // 通知通道
    private static final String CHANNEL_ID = "biliauto_approval";
    private static final int NOTIFY_ID = 8801;

    // 主机名（用于判断 WebView 权限请求来源）
    private static final String HOST_ONLY = BASE_URL.replace("https://", "").replace("http://", "");
    // 放行判断用的地址片段
    private static final String PI_IPV6 = "YOUR_SERVER_IPV6";
    private static final String PI_LAN_IP = "YOUR_SERVER_HOST";
    // 待处理的 WebView 权限请求（等系统权限回调后再放行）
    private android.webkit.PermissionRequest pendingPermRequest = null;
    private static final int REQ_AUDIO = 1002;
    private static final int REQ_OVERLAY = 1003;

    // ===== 悬浮按钮 =====
    private OverlayButtons overlay;
    // =====================

    private WebView web;
    private View splash;
    private TextView splashMsg;
    private LinearLayout errorBox;
    private TextView errorText;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private Runnable watchdog;


    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON,
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= 28) {
            getWindow().getAttributes().layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        }
        if (Build.VERSION.SDK_INT >= 21) {
            getWindow().setStatusBarColor(Color.parseColor("#0b0d11"));
            getWindow().setNavigationBarColor(Color.parseColor("#0b0d11"));
        }

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0b0d11"));

        // ---- WebView ----
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0b0d11"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // 关键：关掉 overview 模式。
        // 开着时 WebView 会把整页缩放到屏幕内 —— 页面一高（比如聊天设置面板）
        // 就被整体缩小居中，字小到看不清，也滚不到底部。
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setBuiltInZoomControls(true);          // 双指缩放
        s.setSupportZoom(true);
        s.setDisplayZoomControls(false);         // 不显示缩放按钮
        s.setTextZoom(100);
        if (Build.VERSION.SDK_INT >= 21) {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
        // 允许 WebView 直接联网（某些定制 ROM 需要）
        s.setAllowFileAccess(false);
        s.setDatabaseEnabled(true);

        // JS 桥：页面脚本有新审批时回调过来弹通知
        web.addJavascriptInterface(new NotifyBridge(), "biliNotify");
        web.addJavascriptInterface(new OverlayBridge(), "biliOverlay");
        // 页面里用 window.__biliNotify 调
        web.evaluateJavascript(
                "window.__biliNotify=function(n,t,d){window.biliNotify.notify(n,t||'',d||'');};", null);

        // WebView 里的语音输入需要显式放行麦克风请求，
        // 否则页面一直拿 null，表现为 not-allowed
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final android.webkit.PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        String origin = request.getOrigin() != null ? request.getOrigin().toString() : "";

                        // 放行判断放宽：只要 origin 里含树莓派的 IP 就算自己人。
                        // 原来的 startsWith(BASE_URL) 太严 —— origin 可能没有尾部斜杠，
                        // 也可能你是用内网 IP 或 localhost 访问的，一律匹配不上。
                        boolean ours = origin.contains(PI_IPV6)
                                    || origin.contains(PI_LAN_IP)
                                    || origin.contains("localhost")
                                    || origin.contains("127.0.0.1");
                        if (!ours) {
                            request.deny();
                            return;
                        }
                        // 系统权限没给就先申请，给完再放行
                        if (!hasAudioPermission()) {
                            pendingPermRequest = request;
                            askAudioPermission();
                            return;
                        }
                        // 只授予麦克风，别的资源（摄像头等）不放
                        java.util.List<String> allow = new java.util.ArrayList<>();
                        for (String res : request.getResources()) {
                            if ("android.webkit.resource.AUDIO_CAPTURE".equals(res)) {
                                allow.add(res);
                            }
                        }
                        if (allow.isEmpty()) {
                            request.deny();
                        } else {
                            request.grant(allow.toArray(new String[0]));
                        }
                    }
                });
            }
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedSslError(WebView v, android.webkit.SslErrorHandler handler,
                                           android.net.http.SslError error) {
                // Pi 用的是自签证书，这里显式信任。
                // 只对我们自己的地址放行，其他站点仍按默认规则拦截。
                String u = (error != null) ? error.getUrl() : null;
                if (u != null && u.startsWith(BASE_URL)) {
                    handler.proceed();
                } else {
                    handler.cancel();
                }
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                cancelWatchdog();
                if (splash != null) splash.setVisibility(View.GONE);
                hideError();
                if (web != null) web.setVisibility(View.VISIBLE);
                // 页面加载完就装轮询（页面里有 signedFetch 才能工作）
                installNotifier();
            }

            @Override
            public void onReceivedError(WebView v, int errorCode, String description,
                                        String failingUrl) {
                // 只有主页面失败才报错，子资源失败忽略
                if (failingUrl != null && failingUrl.startsWith(BASE_URL)) {
                    showError("连不上树莓派\n\n" + description + "\n(错误码 " + errorCode + ")");
                }
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame() && web != null) {
                    String d = (err != null) ? String.valueOf(err.getDescription()) : "未知错误";
                    int code = (err != null) ? err.getErrorCode() : -1;
                    showError("连不上树莓派\n\n" + d + "\n(错误码 " + code + ")");
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                if (url == null) return false;
                if (url.startsWith("http://[") || url.startsWith(BASE_URL)) return false;
                try {
                    startActivity(new android.content.Intent(
                            android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url)));
                } catch (Exception ignored) { }
                return true;
            }
        });
        web.setWebChromeClient(new WebChromeClient());
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));

        // ---- 启动提示 ----
        LinearLayout sp = new LinearLayout(this);
        sp.setOrientation(LinearLayout.VERTICAL);
        sp.setGravity(Gravity.CENTER);
        sp.setBackgroundColor(Color.parseColor("#0b0d11"));

        TextView icon = new TextView(this);
        icon.setText("🐟");
        icon.setTextSize(TypedValue.COMPLEX_UNIT_SP, 36);
        icon.setGravity(Gravity.CENTER);
        sp.addView(icon);

        splashMsg = new TextView(this);
        splashMsg.setText("连接中…");
        splashMsg.setTextColor(Color.parseColor("#8b95a5"));
        splashMsg.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        splashMsg.setGravity(Gravity.CENTER);
        splashMsg.setPadding(20, 14, 20, 0);
        sp.addView(splashMsg);

        splash = sp;
        root.addView(splash, new FrameLayout.LayoutParams(-1, -1));

        // ---- 错误提示 ----
        errorBox = buildErrorBox();
        root.addView(errorBox, new FrameLayout.LayoutParams(-1, -1));
        errorBox.setVisibility(View.GONE);

        setContentView(root);

        requestNotifPermission();
        askAudioPermission();     // 进 App 就把麦克风权限要了，省得用户自己找
        load();
    }

    private LinearLayout buildErrorBox() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor("#0b0d11"));
        box.setPadding(24, 24, 24, 24);

        TextView icon = new TextView(this);
        icon.setText("📡");
        icon.setTextSize(TypedValue.COMPLEX_UNIT_SP, 34);
        icon.setGravity(Gravity.CENTER);
        box.addView(icon);

        errorText = new TextView(this);
        errorText.setText("连不上");
        errorText.setTextColor(Color.parseColor("#e74c3c"));
        errorText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        errorText.setGravity(Gravity.CENTER);
        errorText.setPadding(0, 12, 0, 16);
        box.addView(errorText);

        Button retry = new Button(this);
        retry.setText("重试");
        retry.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                errorBox.setVisibility(View.GONE);
                if (splash != null) splash.setVisibility(View.VISIBLE);
                if (splashMsg != null) splashMsg.setText("重试中…");
                load();
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(200, 84);
        box.addView(retry, lp);

        TextView tip = new TextView(this);
        tip.setText(BASE_URL.replace("https://", ""));
        tip.setTextColor(Color.parseColor("#4b5261"));
        tip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 9);
        tip.setGravity(Gravity.CENTER);
        tip.setPadding(0, 14, 0, 0);
        box.addView(tip);

        return box;
    }

    private void showError(final String msg) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (splash != null) splash.setVisibility(View.GONE);
                if (web != null) web.setVisibility(View.GONE);
                if (errorText != null) errorText.setText(msg);
                if (errorBox != null) errorBox.setVisibility(View.VISIBLE);
            }
        });
    }

    private void hideError() {
        if (errorBox != null) errorBox.setVisibility(View.GONE);
    }

    /** 20 秒看门狗：超时没加载出来就提示 */
    private void startWatchdog() {
        cancelWatchdog();
        watchdog = new Runnable() {
            @Override
            public void run() {
                if (web != null && web.getProgress() < 100) {
                    showError("连接超时\n\n可能原因：\n· 手表没连 IPv6 网络\n· Pi 的地址变了\n· 路由器防火墙拦了入站");
                }
            }
        };
        ui.postDelayed(watchdog, 20000);
    }

    private void cancelWatchdog() {
        if (watchdog != null) {
            ui.removeCallbacks(watchdog);
            watchdog = null;
        }
    }

    private void load() {
        if (web == null) return;
        web.setVisibility(View.VISIBLE);
        web.loadUrl(PAGE);
        startWatchdog();
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    // ======== 待审批通知 ========
    // 在页面里跑定时器轮询 /api/pending，有新审批就调系统通知。
    // 放 JS 里做是因为签名逻辑（HMAC-SHA256）页面里已经有了，
    // Java 侧不用再实现一遍加密。

    private static final String NOTIFY_JS =
        "(function(){"
        + "if(window.__notifyInstalled){return 'already';}"
        + "window.__notifyInstalled=true;"
        + "var lastCount=-1;"
        + "function check(){"
        + "  if(typeof signedFetch!=='function'){return;}"
        + "  signedFetch('GET','/api/pending?status=pending&limit=1').then(function(d){"
        + "    var n=(d&&d.count)||0;"
        + "    if(lastCount>=0&&n>lastCount&&window.__biliNotify){"
        + "      var it=(d.items&&d.items[0])||{};"
        + "      window.__biliNotify(n,it.video_title||'',it.draft||'');"
        + "    }"
        + "    lastCount=n;"
        + "  }).catch(function(){});"
        + "}"
        + "setInterval(check,60000);"
        + "setTimeout(check,3000);"
        + "return 'ok';"
        + "})();";

    private void installNotifier() {
        if (web == null) return;
        if (Build.VERSION.SDK_INT >= 23) {
            web.evaluateJavascript(NOTIFY_JS, null);
        } else {
            web.loadUrl("javascript:" + NOTIFY_JS);
        }
    }

    /** 由 JS 调用：有新审批时弹通知 */
    private class NotifyBridge {
        @android.webkit.JavascriptInterface
        public void notify(int count, String title, String draft) {
            showNotification(count, title, draft);
        }
    }

    // ===================== 悬浮按钮 & DPI =====================

    /** 给网页调用的控制桥。 */
    private class OverlayBridge {

        @android.webkit.JavascriptInterface
        public void showOverlay() {
            ui.post(new Runnable() {
                @Override
                public void run() { startOverlay(); }
            });
        }

        @android.webkit.JavascriptInterface
        public void hideOverlay() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    if (overlay != null) overlay.hide();
                }
            });
        }

        @android.webkit.JavascriptInterface
        public boolean isOverlayShowing() {
            return overlay != null && overlay.isShowing();
        }

        @android.webkit.JavascriptInterface
        public void setPoints(final String json) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    try {
                        List<org.json.JSONObject> list = new ArrayList<org.json.JSONObject>();
                        org.json.JSONArray arr = new org.json.JSONArray(json);
                        for (int i = 0; i < arr.length(); i++) {
                            list.add(arr.getJSONObject(i));
                        }
                        if (overlay == null) {
                            overlay = new OverlayButtons(MainActivity.this, tapListener);
                        }
                        overlay.setPoints(list);
                    } catch (Exception e) {
                        Log.e("BiliOverlay", "setPoints 失败", e);
                    }
                }
            });
        }

        /** 用 Java 算 HMAC 签名（HTTP/HTTPS 都可靠，不依赖 crypto.subtle）。 */
        @android.webkit.JavascriptInterface
        public String sign(String method, String path, String body) {
            try {
                String msg = method.toUpperCase() + "\n" + path + "\n"
                        + (body == null ? "" : body);
                return HmacUtil.sha256Hex(KEY, msg);
            } catch (Exception e) {
                Log.e("BiliSign", "签名失败", e);
                return "";
            }
        }

        @android.webkit.JavascriptInterface
        public boolean canDrawOverlay() {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                return android.provider.Settings.canDrawOverlays(MainActivity.this);
            }
            return true;
        }

        @android.webkit.JavascriptInterface
        public void requestOverlayPermission() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        Intent i = new Intent(
                                android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                android.net.Uri.parse("package:" + getPackageName()));
                        startActivityForResult(i, REQ_OVERLAY);
                    }
                }
            });
        }
    }

    /** 悬浮按钮回调。 */
    private final OverlayButtons.TapListener tapListener = new OverlayButtons.TapListener() {
        @Override
        public void onOverlayTap(String name, int x, int y) {
            Log.i("BiliOverlay", "点击 " + name + " (" + x + "," + y + ")");
            // 延迟一小会儿再注入：面板虽然已经收起，但窗口从全屏缩回浮球
            // 需要时间生效。太早注入的话，点击会落在残留的悬浮窗上，
            // 表现为点不动，或者被当成"点空白处"而收起。
            ui.postDelayed(new Runnable() {
                @Override
                public void run() {
                    new Thread(new Runnable() {
                        @Override
                        public void run() { sendTapToPi(name, x, y); }
                    }).start();
                }
            }, 180);
        }

        @Override
        public void onOverlayHide() {
            Log.i("BiliOverlay", "悬浮层隐藏");
        }

        @Override
        public void onDpiChange(final String mode) {
            Log.i("BiliOverlay", "改 DPI: " + mode);
            new Thread(new Runnable() {
                @Override
                public void run() { sendDpiToPi(mode); }
            }).start();
        }
    };

    private void startOverlay() {
        if (overlay == null) {
            overlay = new OverlayButtons(this, tapListener);
        } else if (overlay.isShowing()) {
            return;
        }
        overlay.show();
    }

    private void sendTapToPi(String name, int x, int y) {
        try {
            String path = "/api/watch/tap";
            String body = "{\"x\":" + x + ",\"y\":" + y + "}";
            String sign = HmacUtil.sha256Hex(KEY, "POST\n" + path + "\n" + body);
            postJson(path, body, sign);
            Log.i("BiliOverlay", "点击 " + name + " 已转发");
        } catch (Exception e) {
            Log.e("BiliOverlay", "转发点击失败", e);
        }
    }

    private void sendDpiToPi(String mode) {
        try {
            String path = "/api/watch/dpi";
            String dpiVal = "reset".equals(mode) ? "\"reset\"" : mode;
            String body = "{\"dpi\":" + dpiVal + "}";
            String sign = HmacUtil.sha256Hex(KEY, "POST\n" + path + "\n" + body);
            postJson(path, body, sign);
            Log.i("BiliOverlay", "DPI 请求已发: " + mode);

            // 改完 DPI 屏幕逻辑尺寸会整体变化，悬浮球原来的坐标可能落到屏幕外。
            // 系统重新布局需要一点时间，这里分几次校准，确保最终位置正确。
            final int[] delays = {300, 800, 1500, 2500};
            for (int i = 0; i < delays.length; i++) {
                final int d = delays[i];
                ui.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        if (overlay != null && overlay.isShowing()) {
                            overlay.onConfigChanged();
                        }
                    }
                }, d);
            }
        } catch (Exception e) {
            Log.e("BiliOverlay", "改 DPI 失败", e);
        }
    }

    /** POST 到 Pi。证书已在 network_security_config 里信任，不需要额外绕过。 */
    private void postJson(String path, String body, String sign) throws Exception {
        java.net.URL url = new java.net.URL(BASE_URL + path);
        java.net.HttpURLConnection c = (java.net.HttpURLConnection) url.openConnection();
        c.setRequestMethod("POST");
        c.setRequestProperty("X-Bili-Sign", sign);
        c.setRequestProperty("Content-Type", "application/json");
        c.setDoOutput(true);
        c.setConnectTimeout(8000);
        c.setReadTimeout(8000);
        c.getOutputStream().write(body.getBytes("UTF-8"));
        int code = c.getResponseCode();
        Log.i("BiliOverlay", "POST " + path + " -> " + code);
        c.disconnect();
    }

    // =========================================================

    private void showNotification(int count, String title, String draft) {
        try {
            NotificationManager nm =
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm == null) return;

            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL_ID, "待审批提醒", NotificationManager.IMPORTANCE_HIGH);
                ch.enableVibration(true);
                nm.createNotificationChannel(ch);
            }

            String text = title.isEmpty() ? ("有 " + count + " 条新草稿待审批")
                                          : (title + "\n" + draft);

            Intent open = new Intent(this, MainActivity.class);
            open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pi = PendingIntent.getActivity(
                    this, 0, open,
                    Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
                                                : PendingIntent.FLAG_UPDATE_CURRENT);

            Notification.Builder b = Build.VERSION.SDK_INT >= 26
                    ? new Notification.Builder(this, CHANNEL_ID)
                    : new Notification.Builder(this);
            b.setContentTitle("🐳 有新评论待审批")
             .setContentText(text)
             .setStyle(new Notification.BigTextStyle().bigText(text))
             .setSmallIcon(android.R.drawable.ic_dialog_info)
             .setAutoCancel(true)
             .setContentIntent(pi);
            if (Build.VERSION.SDK_INT < 26) {
                b.setPriority(Notification.PRIORITY_HIGH);
                b.setDefaults(Notification.DEFAULT_ALL);
            }
            nm.notify(NOTIFY_ID, b.build());
        } catch (Throwable ignored) {
            // 通知失败不能影响主流程
        }
    }

    private void requestNotifPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1001);
            }
        }
    }

    // ---------- 录音权限 ----------

    private boolean hasAudioPermission() {
        if (Build.VERSION.SDK_INT < 23) return true;   // 6.0 以下装的时候就有
        return checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)
                == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    /** 主动弹系统授权框，不用用户自己去设置里点 */
    private void askAudioPermission() {
        if (hasAudioPermission()) return;
        if (Build.VERSION.SDK_INT >= 23) {
            requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);

        if (code == REQ_AUDIO) {
            boolean granted = results.length > 0
                    && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED;
            if (pendingPermRequest != null) {
                try {
                    if (granted) {
                        pendingPermRequest.grant(pendingPermRequest.getResources());
                    } else {
                        pendingPermRequest.deny();
                    }
                } catch (Throwable ignored) {
                }
                pendingPermRequest = null;
            }
            if (!granted) {
                toast("麦克风权限被拒绝。语音输入需要它，可在系统设置里重新开启。");
            }
        }
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req == REQ_OVERLAY) {
            boolean ok = Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                    && android.provider.Settings.canDrawOverlays(this);
            toast(ok ? "悬浮窗权限已授予" : "没有悬浮窗权限，按钮无法显示");
            if (ok) startOverlay();
        }
    }

    private void toast(final String msg) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                android.widget.Toast.makeText(MainActivity.this, msg,
                        android.widget.Toast.LENGTH_LONG).show();
            }
        });
    }

    /**
     * 系统配置变化（改 DPI、旋转、字体缩放等）时，悬浮球的坐标要跟着重算，
     * 否则会落到新的屏幕范围之外，表现为"跑到角落按不着"。
     */
    @Override
    public void onConfigurationChanged(android.content.res.Configuration cfg) {
        super.onConfigurationChanged(cfg);
        Log.i("BiliOverlay", "配置变化，重算悬浮窗位置");
        if (overlay != null && overlay.isShowing()) {
            // 稍等一下，等新尺寸生效后再校准
            ui.postDelayed(new Runnable() {
                @Override
                public void run() {
                    if (overlay != null && overlay.isShowing()) {
                        overlay.onConfigChanged();
                    }
                }
            }, 400);
        }
    }

    @Override
    protected void onDestroy() {
        cancelWatchdog();
        if (web != null) {
            web.loadUrl("about:blank");
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
