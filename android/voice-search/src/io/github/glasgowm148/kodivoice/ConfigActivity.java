package io.github.glasgowm148.kodivoice;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Owner-entered configuration. The token stays in this app's private, non-backed-up storage. */
public class ConfigActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);
        Config config = Config.load(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(64, 36, 64, 36);
        layout.setBackgroundColor(Color.rgb(20, 24, 34));
        TextView title = new TextView(this);
        title.setText("Kodi voice search");
        title.setTextSize(28);
        title.setTextColor(Color.WHITE);
        layout.addView(title);
        TextView details = new TextView(this);
        details.setText("Install Kodi Manager on this TV. Enter its port and token privately here. "
                + "Voice recognition uses your Android speech provider, which may send audio to its service. "
                + "The search text goes only to Kodi Manager on this TV. "
                + "The on-screen mic works without changing your TV's assistant. "
                + "The remote mic button needs a separate assistant selection in Android settings.");
        details.setTextColor(Color.LTGRAY);
        details.setTextSize(17);
        layout.addView(details);
        EditText port = new EditText(this);
        port.setTextColor(Color.WHITE);
        port.setHint("Kodi Manager port");
        port.setInputType(InputType.TYPE_CLASS_NUMBER);
        port.setText(String.valueOf(config.port));
        layout.addView(port);
        EditText token = new EditText(this);
        token.setTextColor(Color.WHITE);
        token.setHintTextColor(Color.LTGRAY);
        token.setHint("Kodi Manager token");
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setText(config.token);
        layout.addView(token);
        TextView status = new TextView(this);
        status.setTextColor(Color.LTGRAY);
        Button save = new Button(this);
        save.setText("Save on this TV");
        save.setOnClickListener(v -> {
            try {
                int chosenPort = Integer.parseInt(port.getText().toString());
                String chosenToken = token.getText().toString().trim();
                if (chosenPort < 1 || chosenPort > 65535 || chosenToken.isEmpty()
                        || chosenToken.contains("\r") || chosenToken.contains("\n")) {
                    throw new IllegalArgumentException();
                }
                Config.save(this, chosenPort, chosenToken);
                status.setText("Saved privately. Open Bingie search and choose Search by voice.");
            } catch (IllegalArgumentException e) {
                status.setText("Enter a port between 1 and 65535 and a non-empty token.");
            }
        });
        layout.addView(save);
        layout.addView(status);
        setContentView(layout, new ViewGroup.LayoutParams(-1, -1));
    }
}
