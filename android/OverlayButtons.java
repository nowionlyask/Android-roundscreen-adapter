package com.biliauto.watch;

import android.content.Context;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 悬浮控制面板：小浮球点开才显示按钮，横排折行，不超出圆屏。
 * 收起时窗口只有浮球大小，不拦截其他应用的触摸。
 */
public class OverlayButtons {

    private static final String TAG = "BiliOverlay";
    private static final int BALL_SIZE = 48;
    private static final int BTN_W = 62;
    private static final int BTN_H = 58;
    private static final int BTN_GAP = 8;
    private static final int PANEL_PAD = 14;
    // 一圈最多放几个按钮，超出的排到内圈
    private static final int MAX_RING = 10;

    public interface TapListener {
        void onOverlayTap(String name, int x, int y);
        void onOverlayHide();
        void onDpiChange(String mode);
    }

    private final Context ctx;
    private final TapListener listener;
    private final WindowManager wm;
    private final Handler ui = new Handler(Looper.getMainLooper());

    private FrameLayout root;
    private View ball;
    private FrameLayout expanded;
    private WindowManager.LayoutParams lp;
    private List<JSONObject> points = new ArrayList<JSONObject>();
    private boolean isOpen = false;

    private int dragStartX, dragStartY, ballStartX, ballStartY;
    private boolean dragging = false;
    private long touchDownTime = 0;

    // 展开前浮球的位置。展开时窗口会铺满全屏、坐标被改成 0，
    // 收起时必须还原回这里，否则会跑到左上角。
    private int savedBallX = 0;
    private int savedBallY = 0;

    public OverlayButtons(Context ctx, TapListener listener) {
        this.ctx = ctx;
        this.listener = listener;
        this.wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
    }

    public boolean isShowing() { return root != null; }

    public void setPoints(List<JSONObject> pts) {
        this.points = pts == null ? new ArrayList<JSONObject>() : pts;
        if (isOpen) rebuildExpanded();
    }

    private int dp(int v) {
        return (int) (v * ctx.getResources().getDisplayMetrics().density);
    }

    public void show() {
        if (root != null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && !android.provider.Settings.canDrawOverlays(ctx)) {
            toast("没有悬浮窗权限");
            return;
        }

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;

        int size = dp(BALL_SIZE);
        lp = new WindowManager.LayoutParams(
                size, size, type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);

        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
        lp.gravity = Gravity.TOP | Gravity.START;
        // 默认放屏幕正中
        lp.x = (sw - size) / 2;
        lp.y = (sh - size) / 2;

        root = new FrameLayout(ctx);
        ball = makeBall();
        root.addView(ball, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        try {
            wm.addView(root, lp);
        } catch (Exception e) {
            Log.e(TAG, "addView 失败", e);
            toast("悬浮窗创建失败：" + e.getMessage());
            root = null;
            return;
        }
        Log.i(TAG, "浮球已显示");
    }

    public void hide() {
        if (root == null) return;
        if (isOpen) collapse();
        try {
            wm.removeView(root);
        } catch (Exception ignored) {}
        root = null;
        ball = null;
        expanded = null;
        isOpen = false;
    }

    private View makeBall() {
        TextView tv = new TextView(ctx);
        tv.setText("≡");
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(14);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setGravity(Gravity.CENTER);

        final GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(Color.parseColor("#EE1E6FD9"));
        bg.setStroke(1, Color.parseColor("#FF4EA8FF"));
        tv.setBackground(bg);

        tv.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent e) {
                int act = e.getActionMasked();
                if (act == MotionEvent.ACTION_DOWN) {
                    dragging = false;
                    touchDownTime = System.currentTimeMillis();
                    dragStartX = (int) e.getRawX();
                    dragStartY = (int) e.getRawY();
                    ballStartX = lp.x;
                    ballStartY = lp.y;
                    bg.setColor(Color.parseColor("#FF2E9BFF"));
                    return true;
                } else if (act == MotionEvent.ACTION_MOVE) {
                    int dx = (int) e.getRawX() - dragStartX;
                    int dy = (int) e.getRawY() - dragStartY;
                    if (Math.abs(dx) > dp(6) || Math.abs(dy) > dp(6)) dragging = true;
                    if (dragging) {
                        lp.x = ballStartX + dx;
                        lp.y = ballStartY + dy;
                        try { wm.updateViewLayout(root, lp); } catch (Exception ignored) {}
                    }
                    return true;
                } else if (act == MotionEvent.ACTION_UP || act == MotionEvent.ACTION_CANCEL) {
                    bg.setColor(Color.parseColor("#EE1E6FD9"));
                    long dur = System.currentTimeMillis() - touchDownTime;
                    if (dragging) {
                        clampInto();
                    } else if (dur < 400) {
                        toggle();
                    }
                    dragging = false;
                    return true;
                }
                return false;
            }
        });
        return tv;
    }

    /**
     * 拖动结束后的处理：**只保证不跑出屏幕，不吸附边缘**。
     * 用户想放哪就放哪，自由移动。
     */
    private void clampInto() {
        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
        int size = dp(BALL_SIZE);
        boolean moved = false;

        if (lp.x + size > sw) { lp.x = sw - size; moved = true; }
        if (lp.x < 0) { lp.x = 0; moved = true; }
        if (lp.y + size > sh) { lp.y = sh - size; moved = true; }
        if (lp.y < 0) { lp.y = 0; moved = true; }

        if (moved) {
            try { wm.updateViewLayout(root, lp); } catch (Exception ignored) {}
        }
    }

    /**
     * DPI 变化后重新校准位置。
     *
     * 原则：**能不动就不动**。
     * 改 DPI 后屏幕逻辑尺寸变了，只要浮球坐标还在新屏幕范围内就保持原样，
     * 只有真的超出去了才夹回最近的可视位置（而不是吸附到某个角落）。
     */
    public void onConfigChanged() {
        if (root == null) return;
        try {
            int sw = ctx.getResources().getDisplayMetrics().widthPixels;
            int sh = ctx.getResources().getDisplayMetrics().heightPixels;

            if (isOpen) {
                lp.width = sw;
                lp.height = sh;
                lp.x = 0;
                lp.y = 0;
                // 展开中改了 DPI：记下的浮球位置也要跟着夹进新屏幕，
                // 否则收起后会还原到屏幕外
                int size2 = dp(BALL_SIZE);
                if (savedBallX + size2 > sw) savedBallX = sw - size2;
                if (savedBallX < 0) savedBallX = 0;
                if (savedBallY + size2 > sh) savedBallY = sh - size2;
                if (savedBallY < 0) savedBallY = 0;
                rebuildExpanded();
            } else {
                int size = dp(BALL_SIZE);
                lp.width = size;
                lp.height = size;
                // 只夹紧，不吸附。超出多少就往回挪多少。
                if (lp.x + size > sw) lp.x = sw - size;
                if (lp.x < 0) lp.x = 0;
                if (lp.y + size > sh) lp.y = sh - size;
                if (lp.y < 0) lp.y = 0;
            }
            wm.updateViewLayout(root, lp);
            Log.i(TAG, "DPI 变化后校准: 屏幕 " + sw + "x" + sh
                    + "  浮球=(" + lp.x + "," + lp.y + ")");
        } catch (Exception e) {
            Log.e(TAG, "configChanged 失败", e);
        }
    }

    private void toggle() { if (isOpen) collapse(); else expand(); }

    private void expand() {
        if (root == null || isOpen) return;
        isOpen = true;

        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;

        // 先记住浮球当前位置，收起时用它还原
        savedBallX = lp.x;
        savedBallY = lp.y;

        lp.width = sw;
        lp.height = sh;
        lp.x = 0;
        lp.y = 0;

        expanded = new FrameLayout(ctx);
        expanded.setBackgroundColor(Color.parseColor("#99000000"));
        expanded.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) { collapse(); }
        });

        rebuildExpanded();
        root.addView(expanded, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        try { wm.updateViewLayout(root, lp); } catch (Exception e) { Log.e(TAG, "expand", e); }
        Log.i(TAG, "已展开");
    }

    private void collapse() {
        if (root == null || !isOpen) return;
        isOpen = false;
        if (expanded != null) {
            root.removeView(expanded);
            expanded = null;
        }
        int size = dp(BALL_SIZE);
        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
        lp.width = size;
        lp.height = size;
        // 还原到展开前的位置（不是展开时的 0,0）
        lp.x = savedBallX;
        lp.y = savedBallY;
        // 只在超出屏幕时才夹回来
        if (lp.x + size > sw) lp.x = sw - size;
        if (lp.x < 0) lp.x = 0;
        if (lp.y + size > sh) lp.y = sh - size;
        if (lp.y < 0) lp.y = 0;
        try { wm.updateViewLayout(root, lp); } catch (Exception e) { Log.e(TAG, "collapse", e); }
        Log.i(TAG, "已收起，还原位置 (" + lp.x + "," + lp.y + ")");
    }

    /**
     * 环形排布：按钮沿着圆周等距摆放，数量多了就自动往里收。
     *
     * 规则：
     * - 一圈最多放 MAX_RING 个，超过的部分排到内圈
     * - 外圈半径随按钮数增加而收缩（保证小屏也点得着）
     * - 按钮尺寸随数量自适应缩小，但有下限
     * - 所有坐标都夹在屏幕内，不超出边界
     */
    private void rebuildExpanded() {
        if (expanded == null) return;
        expanded.removeAllViews();

        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
        int cx = sw / 2;
        int cy = sh / 2;

        int n = points.size();

        if (n == 0) {
            TextView empty = new TextView(ctx);
            empty.setText("还没有点位\n在浏览器里配置");
            empty.setTextColor(Color.parseColor("#C8D0DA"));
            empty.setTextSize(12);
            empty.setGravity(Gravity.CENTER);
            FrameLayout.LayoutParams fp = new FrameLayout.LayoutParams(
                    dp(120), dp(60));
            fp.leftMargin = cx - dp(60);
            fp.topMargin = cy - dp(30);
            expanded.addView(empty, fp);
            return;
        }

        // ---- 按钮尺寸：数量越多越小，但有下限 ----
        int btnSize = dp(52);
        if (n > 4) btnSize = dp(48);
        if (n > 7) btnSize = dp(44);
        if (n > 10) btnSize = dp(40);
        if (n > 14) btnSize = dp(36);

        int fontSize = btnSize >= dp(48) ? 12 : btnSize >= dp(44) ? 11 : 10;

        // ---- 圈层规划 ----
        // 外圈能放的数量：按圆周长估算，保证相邻按钮不重叠
        int maxOuter = Math.max(4, (int) ((2 * Math.PI * (Math.min(sw, sh) / 2.0 - btnSize))
                / (btnSize * 1.15)));
        maxOuter = Math.min(maxOuter, MAX_RING);

        // 外圈半径：
        //  - 基准是半屏减去一个按钮，留边距
        //  - 按钮越多，半径略微收缩，避免贴边难点
        int baseR = Math.min(sw, sh) / 2 - btnSize / 2 - dp(6);
        int shrink = 0;
        if (n > 6) shrink = (n - 6) * dp(1);
        int outerR = Math.max(btnSize, baseR - Math.min(shrink, dp(18)));

        Log.i(TAG, "环形布点: 共 " + n + " 个, 按钮 " + btnSize + "px, 外圈放 "
                + maxOuter + " 个, 半径 " + outerR);

        // ---- 逐个摆放 ----
        int idx = 0;
        int ring = 0;
        while (idx < n) {
            int countThisRing = Math.min(maxOuter, n - idx);
            int radius = outerR - ring * (btnSize + dp(4));
            if (radius < btnSize / 2) radius = btnSize / 2;

            for (int i = 0; i < countThisRing; i++, idx++) {
                JSONObject p = points.get(idx);
                final String nm = p.optString("name", "?");
                final int tx = p.optInt("x", 0);
                final int ty = p.optInt("y", 0);

                // 从 12 点方向开始顺时针均分
                double angle = -Math.PI / 2 + (2 * Math.PI * i / countThisRing);
                int bx = (int) (cx + radius * Math.cos(angle));
                int by = (int) (cy + radius * Math.sin(angle));

                TextView b = ringButton(nm, btnSize, fontSize, ring == 0);
                b.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        if (listener != null) listener.onOverlayTap(nm, tx, ty);
                        flash(v);
                    }
                });

                FrameLayout.LayoutParams fp = new FrameLayout.LayoutParams(
                        btnSize, btnSize);
                // 夹进屏幕，绝不出界
                fp.leftMargin = Math.max(0, Math.min(sw - btnSize, bx - btnSize / 2));
                fp.topMargin = Math.max(0, Math.min(sh - btnSize, by - btnSize / 2));
                expanded.addView(b, fp);
            }
            ring++;
        }

        // ---- 中心：关闭按钮 ----
        int closeSize = dp(40);
        TextView close = ringButton("×", closeSize, 18, false);
        close.setAlpha(0.85f);
        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (listener != null) listener.onOverlayHide();
                collapse();
            }
        });
        FrameLayout.LayoutParams cp = new FrameLayout.LayoutParams(closeSize, closeSize);
        cp.leftMargin = cx - closeSize / 2;
        cp.topMargin = cy - closeSize / 2;
        expanded.addView(close, cp);

        // ---- 中心下方：DPI 控制（小一排） ----
        LinearLayout dpiRow = new LinearLayout(ctx);
        dpiRow.setOrientation(LinearLayout.HORIZONTAL);
        dpiRow.setGravity(Gravity.CENTER);

        String[][] dpis = { {"320","320"}, {"120","120"}, {"100","100"}, {"恢复","reset"} };
        for (int i = 0; i < dpis.length; i++) {
            final String mode = dpis[i][1];
            TextView b = smallButton(dpis[i][0], 10);
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    if (listener != null) listener.onDpiChange(mode);
                    flash(v);
                }
            });
            LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(dp(34), dp(30));
            if (i < dpis.length - 1) blp.rightMargin = dp(4);
            dpiRow.addView(b, blp);
        }

        int rowW = dp(34) * dpis.length + dp(4) * (dpis.length - 1);
        FrameLayout.LayoutParams rlp = new FrameLayout.LayoutParams(
                rowW, dp(30));
        rlp.leftMargin = cx - rowW / 2;
        rlp.topMargin = cy + closeSize / 2 + dp(8);
        // 别超出屏幕底部
        if (rlp.topMargin + dp(30) > sh - dp(8)) {
            rlp.topMargin = cy - closeSize / 2 - dp(38);
        }
        expanded.addView(dpiRow, rlp);
    }

    private LinearLayout newRow() {
        LinearLayout row = new LinearLayout(ctx);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        return row;
    }

    /** 圆环上的按钮：外圈用实心蓝，内圈用浅一点的色区分。 */
    private TextView ringButton(String text, int size, int fontSize, boolean outer) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(fontSize);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setGravity(Gravity.CENTER);
        tv.setMaxLines(2);
        tv.setPadding(dp(2), dp(2), dp(2), dp(2));

        final GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(Color.parseColor(outer ? "#F01E6FD9" : "#E05A4F8C"));
        bg.setStroke(1, Color.parseColor(outer ? "#FF4EA8FF" : "#FF9B8FD0"));
        tv.setBackground(bg);

        tv.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent e) {
                int a = e.getActionMasked();
                if (a == MotionEvent.ACTION_DOWN) {
                    bg.setColor(Color.parseColor("#FF2E9BFF"));
                } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
                    bg.setColor(Color.parseColor(outer ? "#F01E6FD9" : "#E05A4F8C"));
                }
                return false;
            }
        });
        return tv;
    }

    private TextView bigButton(String text) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(12);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setGravity(Gravity.CENTER);
        tv.setMaxLines(2);
        tv.setPadding(dp(3), dp(3), dp(3), dp(3));

        final GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.RECTANGLE);
        bg.setCornerRadius(dp(10));
        bg.setColor(Color.parseColor("#FF1E6FD9"));
        bg.setStroke(1, Color.parseColor("#FF4EA8FF"));
        tv.setBackground(bg);

        tv.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent e) {
                int a = e.getActionMasked();
                if (a == MotionEvent.ACTION_DOWN) {
                    bg.setColor(Color.parseColor("#FF2E9BFF"));
                } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
                    bg.setColor(Color.parseColor("#FF1E6FD9"));
                }
                return false;
            }
        });
        return tv;
    }

    private TextView smallButton(String text, int fontSize) {
        TextView tv = new TextView(ctx);
        tv.setText(text);
        tv.setTextColor(Color.parseColor("#E8ECF4"));
        tv.setTextSize(fontSize);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setGravity(Gravity.CENTER);

        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.RECTANGLE);
        bg.setCornerRadius(dp(8));
        bg.setColor(Color.parseColor("#FF1A2029"));
        bg.setStroke(1, Color.parseColor("#FF2A3140"));
        tv.setBackground(bg);
        return tv;
    }

    private void flash(final View v) {
        v.animate().scaleX(0.9f).scaleY(0.9f).setDuration(80)
                .withEndAction(new Runnable() {
                    @Override
                    public void run() {
                        v.animate().scaleX(1f).scaleY(1f).setDuration(80).start();
                    }
                })
                .start();
    }

    private void toast(final String s) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                Toast.makeText(ctx, s, Toast.LENGTH_SHORT).show();
            }
        });
    }
}
