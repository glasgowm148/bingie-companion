package io.github.glasgowm148.kodivoice;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

import org.json.JSONException;
import org.json.JSONObject;

/** POST /api/search/voice to Kodi Manager on this TV. */
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

    private KodiClient() {
    }

    static Result voiceSearch(Config config, String query) {
        if (!config.ready()) {
            return new Result(false, false, "Not set up: Kodi Manager's token is missing");
        }
        HttpURLConnection http = null;
        try {
            JSONObject body = new JSONObject();
            body.put("query", query);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            http = (HttpURLConnection) new URL("http://127.0.0.1:" + config.port + "/api/search/voice").openConnection();
            http.setConnectTimeout(3000);
            http.setReadTimeout(15000);
            http.setRequestMethod("POST");
            http.setDoOutput(true);
            http.setRequestProperty("Authorization", "Bearer " + config.token);
            http.setRequestProperty("Content-Type", "application/json");
            http.setRequestProperty("Accept", "application/json");
            http.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream out = http.getOutputStream()) {
                out.write(bytes);
            }
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
