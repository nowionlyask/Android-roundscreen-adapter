package com.biliauto.watch;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * HMAC-SHA256 宸ュ叿锛岀敤浜庣粰 Pi 鐨勪腑杞帴鍙ｇ鍚嶃€? *
 * 绛惧悕绠楁硶涓?Pi 绔竴鑷达細
 *   HMAC-SHA256(key, METHOD + "\n" + PATH + "\n" + BODY) 鐨勫崄鍏繘鍒? * key 鏄?pairing.key 鐨勫師濮?64 涓?ASCII 瀛楃锛屼笉鏄?hex 瑙ｇ爜鍚庣殑瀛楄妭銆? */
public final class HmacUtil {

    private HmacUtil() {}

    public static String sha256Hex(String key, String message) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            SecretKeySpec spec = new SecretKeySpec(key.getBytes("UTF-8"), "HmacSHA256");
            mac.init(spec);
            byte[] raw = mac.doFinal(message.getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder(raw.length * 2);
            for (byte b : raw) {
                String h = Integer.toHexString(b & 0xFF);
                if (h.length() == 1) sb.append('0');
                sb.append(h);
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException("HMAC 璁＄畻澶辫触", e);
        }
    }
}

