package io.github.glasgowm148.kodivoice;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Stores Kodi Manager's port and token. Only the adb shell can send this broadcast (the manifest
 * requires the DUMP permission), e.g.
 * {@code am broadcast -n io.github.glasgowm148.kodivoice/.ConfigReceiver -a io.github.glasgowm148.kodivoice.CONFIGURE
 * --ei port 8765 --es token <token>}. The result data is "saved" or "no token".
 */
public class ConfigReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!"io.github.glasgowm148.kodivoice.CONFIGURE".equals(intent.getAction())) {
            return;
        }
        Integer port = intent.hasExtra("port") ? intent.getIntExtra("port", Config.DEFAULT_PORT) : null;
        Config.save(context, port, intent.getStringExtra("token"));
        boolean ready = Config.load(context).ready();
        setResultCode(ready ? 1 : 0);
        setResultData(ready ? "saved" : "no token");
    }
}
