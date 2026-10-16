import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.ComponentName;
import android.os.Handler;
import android.os.HandlerThread;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Ask the offline handoff app to reopen Kodi; no shell identity or remote API. */
public final class KodiProfileLauncher {
    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !("arm".equals(args[0]) || "cancel".equals(args[0]) || "ready".equals(args[0]))) System.exit(2);
        android.os.Looper.prepareMainLooper();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Method create = activityThread.getDeclaredMethod("systemMain"); create.setAccessible(true);
        Object thread = create.invoke(null);
        Method getContext = activityThread.getDeclaredMethod("getSystemContext"); getContext.setAccessible(true);
        Context own = ((Context) getContext.invoke(thread)).createPackageContext("org.xbmc.kodi", 0);
        String token = new String(Files.readAllBytes(Paths.get(args[1])), StandardCharsets.UTF_8);
        Intent request = new Intent("org.kodimanager.profileswitch." + args[0].toUpperCase(java.util.Locale.ROOT))
            .setComponent(new ComponentName("org.kodimanager.profileswitch", "org.kodimanager.profileswitch.ArmReceiver"))
            .addFlags(Intent.FLAG_RECEIVER_FOREGROUND).putExtra("token", token);
        HandlerThread callbacks = new HandlerThread("KodiHandoffReply"); callbacks.start();
        final CountDownLatch done = new CountDownLatch(1);
        final int[] result = {0};
        final String[] protocol = {null};
        own.sendOrderedBroadcast(request, null, new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                result[0] = getResultCode(); protocol[0] = getResultData(); done.countDown();
            }
        }, new Handler(callbacks.getLooper()), 0, null, null);
        boolean received = done.await(4, TimeUnit.SECONDS); callbacks.quitSafely();
        if (!received || result[0] != -1 || !"shutdown-ready-v2".equals(protocol[0])) {
            System.out.println("relaunch_helper_unavailable"); System.exit(2);
        }
        System.out.println("arm".equals(args[0]) ? "handoff_armed" :
            "ready".equals(args[0]) ? "launch_scheduled" : "alarm_cancelled");
    }
}
