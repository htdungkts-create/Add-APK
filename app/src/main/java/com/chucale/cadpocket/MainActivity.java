package com.chucale.cadpocket;

import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import org.json.JSONObject;

import java.io.*;
import java.nio.charset.StandardCharsets;

public class MainActivity extends Activity {
    private static final int REQ_OPEN_DWG = 1001;
    private static final int MAX_FILE_MB = 80;
    private WebView webView;
    private File selectedFile;
    private String selectedName = "";
    private long selectedSize = 0;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMediaPlaybackRequiresUserGesture(true);

        webView.addJavascriptInterface(new Bridge(), "Android");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("https".equals(uri.getScheme()) && "appassets.local".equals(uri.getHost())) {
                    String p = uri.getPath();
                    if (p == null || p.equals("/")) p = "/index.html";
                    if (p.startsWith("/")) p = p.substring(1);
                    try {
                        InputStream in = getAssets().open(p);
                        String mime = mimeFor(p);
                        String enc = mime.startsWith("text/") || mime.contains("javascript") || mime.contains("json") ? "UTF-8" : null;
                        return new WebResourceResponse(mime, enc, in);
                    } catch (IOException ignored) {
                        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", null,
                                new ByteArrayInputStream("Not found".getBytes(StandardCharsets.UTF_8)));
                    }
                }
                return super.shouldInterceptRequest(view, request);
            }
        });
        webView.loadUrl("https://appassets.local/index.html");
    }

    private String mimeFor(String p) {
        String x = p.toLowerCase();
        if (x.endsWith(".html")) return "text/html";
        if (x.endsWith(".js") || x.endsWith(".mjs")) return "application/javascript";
        if (x.endsWith(".wasm")) return "application/wasm";
        if (x.endsWith(".json")) return "application/json";
        if (x.endsWith(".css")) return "text/css";
        return "application/octet-stream";
    }

    public class Bridge {
        @JavascriptInterface
        public void pickDwg() {
            runOnUiThread(() -> {
                Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                startActivityForResult(i, REQ_OPEN_DWG);
            });
        }

        @JavascriptInterface
        public String readChunk(long offset, int length) {
            if (selectedFile == null) return "";
            int safe = Math.max(1, Math.min(length, 512 * 1024));
            try (RandomAccessFile raf = new RandomAccessFile(selectedFile, "r")) {
                if (offset >= raf.length()) return "";
                raf.seek(offset);
                byte[] b = new byte[(int)Math.min(safe, raf.length() - offset)];
                int n = raf.read(b);
                if (n <= 0) return "";
                if (n != b.length) {
                    byte[] c = new byte[n];
                    System.arraycopy(b, 0, c, 0, n);
                    b = c;
                }
                return Base64.encodeToString(b, Base64.NO_WRAP);
            } catch (Exception e) {
                return "";
            }
        }

        @JavascriptInterface public long getSelectedSize() { return selectedSize; }
        @JavascriptInterface public String getSelectedName() { return selectedName; }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_OPEN_DWG || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        String name = queryName(uri);
        if (name == null) name = "selected.dwg";
        if (!name.toLowerCase().endsWith(".dwg")) {
            notifyJs("window.CCL && CCL.nativeError(" + JSONObject.quote("Vui lòng chọn file .dwg") + ")");
            return;
        }
        File out = new File(getCacheDir(), "selected.dwg");
        long total = 0;
        try (InputStream in = getContentResolver().openInputStream(uri); OutputStream os = new FileOutputStream(out)) {
            byte[] buf = new byte[1024 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                total += n;
                if (total > (long)MAX_FILE_MB * 1024 * 1024) throw new IOException("File exceeds phone prototype limit of " + MAX_FILE_MB + " MB");
                os.write(buf, 0, n);
            }
            selectedFile = out;
            selectedName = name;
            selectedSize = total;
            final String js = "window.CCL && CCL.fileReady(" + JSONObject.quote(name) + "," + total + ")";
            notifyJs(js);
        } catch (Exception e) {
            selectedFile = null;
            selectedSize = 0;
            notifyJs("window.CCL && CCL.nativeError(" + JSONObject.quote(e.getMessage()) + ")");
        }
    }

    private String queryName(Uri uri) {
        try (Cursor c = getContentResolver().query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (i >= 0) return c.getString(i);
            }
        } catch (Exception ignored) {}
        return uri.getLastPathSegment();
    }

    private void notifyJs(String js) {
        runOnUiThread(() -> webView.evaluateJavascript(js, null));
    }
}
