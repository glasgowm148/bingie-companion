package io.github.glasgowm148.kodivoice;

import android.content.Context;
import android.content.SharedPreferences;

/** Kodi Manager's local port and bearer token, kept in this app's private preferences. */
final class Config {
    static final int DEFAULT_PORT = 8765;
    private static final String PREFS = "kodivoice";

    final int port;
    final String token;

    private Config(int port, String token) {
        this.port = port;
        this.token = token;
    }

    static Config load(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return new Config(prefs.getInt("port", DEFAULT_PORT), prefs.getString("token", ""));
    }

    static void save(Context context, Integer port, String token) {
        SharedPreferences.Editor editor = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit();
        if (port != null) {
            editor.putInt("port", port);
        }
        if (token != null) {
            editor.putString("token", token);
        }
        editor.commit();
    }

    boolean ready() {
        return token != null && !token.isEmpty() && port > 0 && port < 65536;
    }
}
