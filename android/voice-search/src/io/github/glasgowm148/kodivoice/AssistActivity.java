package io.github.glasgowm148.kodivoice;

import android.Manifest;
import android.app.Activity;
import android.app.SearchManager;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognitionService;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

/**
 * The mic button: listen, then search for the words in the app that was in front when it was
 * pressed (its own search screen, e.g. SmartTube), or in Kodi through Kodi Manager.
 */
public class AssistActivity extends Activity implements RecognitionListener {
    static final String TAG = "KodiVoice";
    static final String KODI = "org.xbmc.kodi";
    static final String EXTRA_QUERY = "query";
    static final String EXTRA_TARGET = "target";
    private static final int ASK_MIC = 1;
    // Google's speech services, preferred over whichever Android lists first.
    private static final String[] PREFERRED = {"com.google.android.katniss", "com.google.android.tts"};

    private final Handler ui = new Handler(Looper.getMainLooper());
    private SpeechRecognizer recognizer;
    private TextView status;
    private TextView heard;
    private String target;
    private boolean finished;
    // Each mic press is a session; work still running for an earlier one is ignored.
    private int session;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        buildUi();
        start(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        stopListening();
        finished = false;
        start(intent);
    }

    private void start(Intent intent) {
        session++;
        target = targetOf(intent);
        Log.i(TAG, "start: target=" + target);
        if ((target == null || KODI.equals(target) || getPackageName().equals(target))
                && !Config.load(this).ready()) {
            startActivity(new Intent(this, ConfigActivity.class));
            finish();
            return;
        }
        String query = intent.getStringExtra(EXTRA_QUERY);
        if (query != null && !query.trim().isEmpty()) {
            deliver(query.trim());
        } else if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            show("Allow the microphone to search by voice", "");
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, ASK_MIC);
        } else {
            listen();
        }
    }

    /** The app that was in front: the assist extra, or an explicit "target" (adb, tests). */
    static String targetOf(Intent intent) {
        String explicit = intent.getStringExtra(EXTRA_TARGET);
        if (explicit != null && !explicit.isEmpty()) {
            return explicit;
        }
        return intent.getStringExtra(Intent.EXTRA_ASSIST_PACKAGE);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        if (code != ASK_MIC) {
            return;
        }
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            listen();
        } else {
            fail("The microphone is not allowed for Kodi voice search");
        }
    }

    // --- listening ------------------------------------------------------------------------------

    private ComponentName recognitionService() {
        List<ResolveInfo> services = getPackageManager().queryIntentServices(
                new Intent(RecognitionService.SERVICE_INTERFACE), 0);
        List<ComponentName> found = new ArrayList<>();
        for (ResolveInfo info : services) {
            if (info.serviceInfo != null && info.serviceInfo.enabled && info.serviceInfo.applicationInfo.enabled) {
                found.add(new ComponentName(info.serviceInfo.packageName, info.serviceInfo.name));
            }
        }
        for (String pkg : PREFERRED) {
            for (ComponentName name : found) {
                if (name.getPackageName().equals(pkg)) {
                    return name;
                }
            }
        }
        return found.isEmpty() ? null : found.get(0);
    }

    private void listen() {
        ComponentName service = recognitionService();
        Log.i(TAG, "speech service: " + service);
        if (service == null) {
            fail("No speech service: enable the Google app (Settings → Apps)");
            return;
        }
        // An explicit service: Android 11 only falls back to a default one when a setting names it.
        recognizer = SpeechRecognizer.createSpeechRecognizer(this, service);
        recognizer.setRecognitionListener(this);
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        intent.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, getPackageName());
        show("Listening…", "");
        recognizer.startListening(intent);
    }

    private void stopListening() {
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
    }

    @Override
    public void onReadyForSpeech(Bundle params) {
        show("Listening…", "");
    }

    @Override
    public void onBeginningOfSpeech() {
    }

    @Override
    public void onRmsChanged(float rmsdB) {
    }

    @Override
    public void onBufferReceived(byte[] buffer) {
    }

    @Override
    public void onEndOfSpeech() {
        show("One moment…", heard.getText().toString());
    }

    @Override
    public void onPartialResults(Bundle partial) {
        String text = first(partial);
        if (text != null) {
            setHeard(text);
        }
    }

    @Override
    public void onResults(Bundle results) {
        String text = first(results);
        stopListening();
        if (text == null || text.trim().isEmpty()) {
            fail("Didn't catch that");
        } else {
            deliver(text.trim());
        }
    }

    @Override
    public void onError(int error) {
        Log.w(TAG, "speech error " + error);
        stopListening();
        switch (error) {
            case SpeechRecognizer.ERROR_NO_MATCH:
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT:
                fail("Didn't catch that");
                break;
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS:
                fail("The speech service may not use the microphone");
                break;
            case SpeechRecognizer.ERROR_NETWORK:
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT:
                fail("Speech needs the internet");
                break;
            default:
                fail("Speech service error " + error);
        }
    }

    @Override
    public void onEvent(int eventType, Bundle params) {
    }

    private static String first(Bundle bundle) {
        ArrayList<String> list = bundle == null ? null : bundle.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        return list == null || list.isEmpty() ? null : list.get(0);
    }

    // --- searching ------------------------------------------------------------------------------

    private void deliver(String text) {
        show("Searching for “" + text + "”", "");
        // The app in front searches itself when it has a search screen (Kodi's only searches its
        // own video library, so Kodi always goes through Kodi Manager).
        if (target != null && !KODI.equals(target) && !getPackageName().equals(target)) {
            Intent search = new Intent(Intent.ACTION_SEARCH).setPackage(target)
                    .putExtra(SearchManager.QUERY, text).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (getPackageManager().resolveActivity(search, 0) != null) {
                Log.i(TAG, "search in " + target);
                startActivity(search);
                done();
                return;
            }
        }
        final Config config = Config.load(this);
        final boolean kodiInFront = KODI.equals(target);
        final int mine = session;
        new Thread(() -> {
            KodiClient.Result result = KodiClient.voiceSearch(config, text);
            if (result.unreachable) {
                // Kodi is not running: start it and wait for Kodi Manager (up to ~40 s).
                ui.post(this::openKodi);
                for (int i = 0; i < 40 && result.unreachable && !finished && mine == session; i++) {
                    sleep(1000);
                    result = KodiClient.voiceSearch(config, text);
                }
            }
            final KodiClient.Result last = result;
            ui.post(() -> {
                if (mine != session) {
                    return;   // a newer mic press took over
                }
                if (last.ok) {
                    if (!kodiInFront) {
                        openKodi();
                    }
                    done();
                } else {
                    fail(last.message);
                }
            });
        }, "kodivoice-search").start();
    }

    private void openKodi() {
        Intent launch = getPackageManager().getLaunchIntentForPackage(KODI);
        if (launch == null) {
            launch = getPackageManager().getLeanbackLaunchIntentForPackage(KODI);
        }
        if (launch != null) {
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            startActivity(launch);
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // --- screen ---------------------------------------------------------------------------------

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        LinearLayout pill = new LinearLayout(this);
        pill.setOrientation(LinearLayout.VERTICAL);
        pill.setGravity(Gravity.CENTER_HORIZONTAL);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.argb(245, 20, 24, 34));
        background.setStroke(dp(1), Color.rgb(0, 102, 255));
        background.setCornerRadius(dp(28));
        pill.setBackground(background);
        pill.setPadding(dp(32), dp(16), dp(32), dp(16));
        status = text(22, Color.WHITE);
        heard = text(18, Color.rgb(190, 190, 190));
        pill.addView(status);
        pill.addView(heard);
        FrameLayout.LayoutParams where = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        where.bottomMargin = dp(48);
        root.addView(pill, where);
        setContentView(root);
    }

    private TextView text(int sp, int color) {
        TextView view = new TextView(this);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(color);
        view.setGravity(Gravity.CENTER_HORIZONTAL);
        return view;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void show(String line, String detail) {
        status.setText("🎙  " + line);
        setHeard(detail);
    }

    private void setHeard(String text) {
        heard.setText(text);
        heard.setVisibility(text == null || text.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
    }

    private void fail(String message) {
        Log.w(TAG, message);
        show(message, "");
        final int mine = session;
        ui.postDelayed(() -> {
            if (mine == session) {
                done();
            }
        }, 3500);
    }

    private void done() {
        if (!finished) {
            finished = true;
            stopListening();
            finish();
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            done();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        finished = true;
        stopListening();
        super.onDestroy();
    }
}
