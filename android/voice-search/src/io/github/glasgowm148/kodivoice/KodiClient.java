package io.github.glasgowm148.kodivoice;

import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * POST /api/search/voice to Kodi Manager on this TV.
 *
 * <p>Any app can listen on 127.0.0.1 while Kodi is stopped, so the bearer token is only sent after
 * whatever answers on the port proves it already knows the token: it must return
 * HMAC-SHA256(token, "kodi-manager-identity-v1:" + nonce) for a fresh random nonce
 * ({@code POST /api/identity/proof}, Kodi Manager 0.7.43+, no Authorization header).
 */
final class KodiClient {
    static final class Result {
        final boolean ok;
        final boolean unreachable;
        final String message;

        Result(boolean ok, boolean unreachable, String message) {
            this.ok = ok;
            this.unreachable = unreachable;
            this.message = message;
        }
    }

    private static final String TAG = "KodiVoice";
    private static final String PROOF_PREFIX = "kodi-manager-identity-v1:";
    private static final char[] HEX = "0123456789abcdef".toCharArray();
    private static final SecureRandom RANDOM = new SecureRandom();

    private KodiClient() {
    }

    static Result voiceSearch(Config config, String query) {
        if (!config.ready()) {
            return new Result(false, false, "Not set up: Kodi Manager's token is missing");
        }
        Result refused = checkIdentity(config);
        if (refused != null) {
            return refused;
        }
        HttpURLConnection http = null;
        try {
            JSONObject body = new JSONObject();
            body.put("query", query);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            http = post(config.port, "/api/search/voice", bytes);
            http.setRequestProperty("Authorization", "Bearer " + config.token);
            send(http, bytes);
            int status = http.getResponseCode();
            String text = read(status >= 400 ? http.getErrorStream() : http.getInputStream());
            JSONObject reply = text.isEmpty() ? new JSONObject() : new JSONObject(text);
            if (status == 200 && reply.optBoolean("ok")) {
                JSONObject data = reply.optJSONObject("data");
                if (data != null && data.optBoolean("opened")) {
                    return new Result(true, false, "");
                }
                return new Result(false, false, "Kodi could not search: " + (data == null ? "?" : data.optString("reason")));
            }
            JSONObject error = reply.optJSONObject("error");
            return new Result(false, false, "Kodi Manager said " + status
                    + (error == null ? "" : ": " + error.optString("message", error.optString("code"))));
        } catch (ConnectException e) {
            return new Result(false, true, "Kodi is not running");
        } catch (IOException | JSONException e) {
            return new Result(false, false, "Kodi Manager did not answer (" + e.getClass().getSimpleName() + ")");
        } finally {
            if (http != null) {
                http.disconnect();
            }
        }
    }

    /**
     * Asks whatever listens on the port to prove it knows the token, without sending the token.
     * Returns null when the proof is right, otherwise the result to report (the token is not sent).
     */
    private static Result checkIdentity(Config config) {
        String refused = "Something else answered on port " + config.port + "; the token was not sent";
        HttpURLConnection http = null;
        try {
            byte[] raw = new byte[32];
            RANDOM.nextBytes(raw);
            String nonce = hex(raw);
            JSONObject body = new JSONObject();
            body.put("nonce", nonce);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            http = post(config.port, "/api/identity/proof", bytes);
            send(http, bytes);
            int status = http.getResponseCode();
            if (status == 404) {
                return new Result(false, false, "Kodi Manager 0.7.43 or later is needed for voice search");
            }
            if (status != 200) {
                Log.w(TAG, "identity check: HTTP " + status);
                return new Result(false, false, refused);
            }
            String text = read(http.getInputStream());
            JSONObject reply = text.isEmpty() ? new JSONObject() : new JSONObject(text);
            JSONObject data = reply.optJSONObject("data");
            Object proof = data == null ? null : data.opt("proof");
            if (!reply.optBoolean("ok") || !(proof instanceof String)) {
                Log.w(TAG, "identity check: no proof in the reply");
                return new Result(false, false, refused);
            }
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(config.token.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] expected = hex(mac.doFinal((PROOF_PREFIX + nonce).getBytes(StandardCharsets.US_ASCII)))
                    .getBytes(StandardCharsets.US_ASCII);
            byte[] given = ((String) proof).getBytes(StandardCharsets.UTF_8);
            if (!MessageDigest.isEqual(expected, given)) {
                Log.w(TAG, "identity check: wrong proof");
                return new Result(false, false, refused);
            }
            return null;
        } catch (ConnectException e) {
            return new Result(false, true, "Kodi is not running");
        } catch (IOException | JSONException | GeneralSecurityException | RuntimeException e) {
            Log.w(TAG, "identity check failed: " + e.getClass().getSimpleName());
            return new Result(false, false, refused);
        } finally {
            if (http != null) {
                http.disconnect();
            }
        }
    }

    /** A JSON POST to Kodi Manager on this TV; redirects are not followed. */
    private static HttpURLConnection post(int port, String path, byte[] bytes) throws IOException {
        HttpURLConnection http = (HttpURLConnection) new URL("http://127.0.0.1:" + port + path).openConnection();
        http.setConnectTimeout(3000);
        http.setReadTimeout(15000);
        http.setInstanceFollowRedirects(false);
        http.setUseCaches(false);
        http.setRequestMethod("POST");
        http.setDoOutput(true);
        http.setRequestProperty("Content-Type", "application/json");
        http.setRequestProperty("Accept", "application/json");
        http.setFixedLengthStreamingMode(bytes.length);
        return http;
    }

    private static void send(HttpURLConnection http, byte[] bytes) throws IOException {
        try (OutputStream out = http.getOutputStream()) {
            out.write(bytes);
        }
    }

    private static String hex(byte[] bytes) {
        char[] out = new char[bytes.length * 2];
        for (int i = 0; i < bytes.length; i++) {
            out[2 * i] = HEX[(bytes[i] >> 4) & 0xf];
            out[2 * i + 1] = HEX[bytes[i] & 0xf];
        }
        return new String(out);
    }

    private static String read(InputStream in) throws IOException {
        if (in == null) {
            return "";
        }
        try (InputStream stream = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int n;
            while ((n = stream.read(buffer)) > 0 && out.size() < 1_000_000) {
                out.write(buffer, 0, n);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }
}
