package com.telemetry.client;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.OutputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;


/**
 * TelemetryClient - The Silent Observer
 * 
 * Tracks player death events and sends data to the Overseer server.
 * All operations are asynchronous and fire-and-forget.
 * 
 * Usage:
 * 1. Call TelemetryClient.register() to register/login the player
 * 2. Call TelemetryClient.startSession() when a play session begins
 * 3. Call TelemetryClient.onPlayerDeath() when the player dies
 * 4. Call TelemetryClient.endSession() when the session ends
 */
public class TelemetryClient {

    // ========================================================================
    // CONFIG
    // ========================================================================
    private static final String OVERSEER_HOST = "http://127.0.0.1:8090";
    private static final int TIMEOUT_MS = 2000;

    // ========================================================================
    // STATE
    // ========================================================================
    private static int sessionId = -1;
    private static int playerId = -1;
    private static int saveId = -1;
    private static ExecutorService executor = null;
    private static boolean initialized = false;

    private static final ConcurrentLinkedQueue<String> deathQueue = new ConcurrentLinkedQueue<>();
    private static final ConcurrentLinkedQueue<String> eventQueue = new ConcurrentLinkedQueue<>();
    private static final int BATCH_SIZE = 15;

    // ========================================================================
    // REGISTRATION & SESSION
    // ========================================================================

    /**
     * Register a player with the Overseer. Must be called before startSession.
     * Returns the player_id assigned by the server.
     * 
     * @param username Player's unique username
     * @param password Player's password
     */
    public static void register(String username, String password) {
        if (executor == null) {
            executor = Executors.newSingleThreadExecutor();
        }

        String payload = String.format(
                "{\"username\":\"%s\",\"password\":\"%s\"}",
                username, password);

        // Synchronous so we can capture player_id before proceeding
        String response = sendSyncWithResponse("/player/register", payload);
        if (response != null) {
            // Parse player_id from response JSON (simple extraction)
            int idIdx = response.indexOf("\"player_id\":");
            if (idIdx >= 0) {
                String sub = response.substring(idIdx + 12).trim();
                StringBuilder num = new StringBuilder();
                for (char c : sub.toCharArray()) {
                    if (Character.isDigit(c)) num.append(c);
                    else break;
                }
                if (num.length() > 0) {
                    playerId = Integer.parseInt(num.toString());
                }
            }
        }

        System.out.println("[Telemetry] Player registered: " + username + " (id=" + playerId + ")");
    }

    /**
     * Upload or update a save file for the current player.
     * 
     * @param slotNumber     Save slot number
     * @param completionPct  Completion percentage (0.00 - 100.00)
     */
    public static void uploadSave(int slotNumber, float completionPct) {
        if (playerId < 0) {
            System.err.println("[Telemetry] Must register before uploading saves");
            return;
        }

        String payload = String.format(
                "{\"player_id\":%d,\"slot_number\":%d,\"completion_pct\":%.2f}",
                playerId, slotNumber, completionPct);

        String response = sendSyncWithResponse("/save/upload", payload);
        if (response != null) {
            int idIdx = response.indexOf("\"save_id\":");
            if (idIdx >= 0) {
                String sub = response.substring(idIdx + 10).trim();
                StringBuilder num = new StringBuilder();
                for (char c : sub.toCharArray()) {
                    if (Character.isDigit(c)) num.append(c);
                    else break;
                }
                if (num.length() > 0) {
                    saveId = Integer.parseInt(num.toString());
                }
            }
        }

        System.out.println("[Telemetry] Save uploaded: slot " + slotNumber + " (save_id=" + saveId + ")");
    }

    /**
     * Start a new telemetry session. Call register() first.
     * Optionally call uploadSave() before this to link the session to a save file.
     */
    public static void startSession() {
        if (playerId < 0) {
            System.err.println("[Telemetry] Must register before starting session");
            return;
        }

        if (initialized) {
            System.out.println("[Telemetry] Already in a session");
            return;
        }

        if (executor == null) {
            executor = Executors.newSingleThreadExecutor();
        }
        initialized = true;

        String payload;
        if (saveId >= 0) {
            payload = String.format(
                    "{\"player_id\":%d,\"save_id\":%d}",
                    playerId, saveId);
        } else {
            payload = String.format(
                    "{\"player_id\":%d}",
                    playerId);
        }

        String response = sendSyncWithResponse("/session/start", payload);
        if (response != null) {
            int idIdx = response.indexOf("\"session_id\":");
            if (idIdx >= 0) {
                String sub = response.substring(idIdx + 13).trim();
                StringBuilder num = new StringBuilder();
                for (char c : sub.toCharArray()) {
                    if (Character.isDigit(c)) num.append(c);
                    else break;
                }
                if (num.length() > 0) {
                    sessionId = Integer.parseInt(num.toString());
                }
            }
        }

        System.out.println("[Telemetry] Session started: " + sessionId);
    }

    /**
     * Shutdown the telemetry system. Call this when the game closes.
     */
    public static void endSession() {
        if (!initialized)
            return;

        // Flush remaining queues
        flushDeathQueue();
        flushEventQueue();

        // End session
        String payload = String.format("{\"session_id\":%d}", sessionId);
        sendSync("/session/end", payload);

        if (executor != null) {
            executor.shutdown();
            executor = null;
        }

        initialized = false;
        sessionId = -1;
        System.out.println("[Telemetry] Session ended");
    }

    // ========================================================================
    // DEATH EVENT TRACKING
    // ========================================================================

    /**
     * Track player death.
     * 
     * @param deathX     Death X coordinate
     * @param deathY     Death Y coordinate
     * @param deathCause What killed the player
     * @param areaCode   Map zone area code (use -1 if unknown)
     */
    public static void onPlayerDeath(float deathX, float deathY, String deathCause, int areaCode) {
        if (!initialized)
            return;

        String payload;
        if (areaCode >= 0) {
            payload = String.format(
                    "{\"session_id\":%d,\"area_code\":%d,\"death_x\":%.2f,\"death_y\":%.2f,\"death_cause\":\"%s\"}",
                    sessionId, areaCode, deathX, deathY, deathCause);
        } else {
            payload = String.format(
                    "{\"session_id\":%d,\"death_x\":%.2f,\"death_y\":%.2f,\"death_cause\":\"%s\"}",
                    sessionId, deathX, deathY, deathCause);
        }

        deathQueue.add(payload);

        if (deathQueue.size() >= BATCH_SIZE) {
            flushDeathQueue();
        }
    }

    /**
     * Convenience overload without area code.
     */
    public static void onPlayerDeath(float deathX, float deathY, String deathCause) {
        onPlayerDeath(deathX, deathY, deathCause, -1);
    }

    // ========================================================================
    // GENERIC EVENT TRACKING
    // ========================================================================

    /**
     * Track a generic player event.
     *
     * @param eventType  Event type string (e.g. "ITEM_PICKUP", "CHECKPOINT", "LEVEL_COMPLETE")
     * @param eventX     Event X coordinate (nullable, pass Float.MIN_VALUE to omit)
     * @param eventY     Event Y coordinate (nullable, pass Float.MIN_VALUE to omit)
     * @param eventValue Optional integer value (e.g. score, damage amount; use -1 to omit)
     * @param areaCode   Map zone area code (use -1 if unknown)
     */
    public static void sendEvent(String eventType, float eventX, float eventY, int eventValue, int areaCode) {
        if (!initialized)
            return;

        StringBuilder sb = new StringBuilder();
        sb.append(String.format("{\"session_id\":%d,\"event_type\":\"%s\"", sessionId, eventType));
        if (areaCode >= 0) {
            sb.append(String.format(",\"area_code\":%d", areaCode));
        }
        if (eventX != Float.MIN_VALUE) {
            sb.append(String.format(",\"event_x\":%.2f", eventX));
        }
        if (eventY != Float.MIN_VALUE) {
            sb.append(String.format(",\"event_y\":%.2f", eventY));
        }
        if (eventValue >= 0) {
            sb.append(String.format(",\"event_value\":%d", eventValue));
        }
        sb.append("}");

        eventQueue.add(sb.toString());

        if (eventQueue.size() >= BATCH_SIZE) {
            flushEventQueue();
        }
    }

    /**
     * Convenience: event with coordinates only.
     */
    public static void sendEvent(String eventType, float eventX, float eventY) {
        sendEvent(eventType, eventX, eventY, -1, -1);
    }

    /**
     * Convenience: event with coordinates and area code.
     */
    public static void sendEvent(String eventType, float eventX, float eventY, int areaCode) {
        sendEvent(eventType, eventX, eventY, -1, areaCode);
    }

    // ========================================================================
    // QUEUE FLUSHING
    // ========================================================================

    private static void flushDeathQueue() {
        if (deathQueue.isEmpty())
            return;

        StringBuilder batch = new StringBuilder("[");
        String event;
        boolean first = true;

        while ((event = deathQueue.poll()) != null) {
            if (!first)
                batch.append(",");
            batch.append(event);
            first = false;
        }
        batch.append("]");

        sendAsync("/death/batch", batch.toString());
    }

    private static void flushEventQueue() {
        if (eventQueue.isEmpty())
            return;

        StringBuilder batch = new StringBuilder("[");
        String event;
        boolean first = true;

        while ((event = eventQueue.poll()) != null) {
            if (!first)
                batch.append(",");
            batch.append(event);
            first = false;
        }
        batch.append("]");

        sendAsync("/event/batch", batch.toString());
    }

    // ========================================================================
    // CORE SENDING LOGIC
    // ========================================================================

    /**
     * Send data asynchronously (fire and forget).
     */
    private static void sendAsync(String endpoint, String jsonPayload) {
        try {
            if (executor == null || executor.isShutdown())
                return;

            executor.submit(() -> sendSync(endpoint, jsonPayload));
        } catch (Exception e) {
            System.err.println("[Telemetry] Connection failed: " + e.getMessage());
        }
    }

    /**
     * Send data synchronously (blocks until complete). No response captured.
     */
    private static void sendSync(String endpoint, String jsonPayload) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(OVERSEER_HOST + endpoint);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(TIMEOUT_MS);
            conn.setReadTimeout(TIMEOUT_MS);

            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonPayload.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }

            int responseCode = conn.getResponseCode();
            if (responseCode != 200) {
                System.err.println("[Telemetry] Server returned: " + responseCode);
            }
        } catch (Exception e) {
            System.err.println("[Telemetry] Send failed: " + e.getMessage());
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    /**
     * Send data synchronously and return the response body.
     */
    private static String sendSyncWithResponse(String endpoint, String jsonPayload) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(OVERSEER_HOST + endpoint);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(TIMEOUT_MS);
            conn.setReadTimeout(TIMEOUT_MS);

            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonPayload.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }

            int responseCode = conn.getResponseCode();
            if (responseCode == 200) {
                BufferedReader br = new BufferedReader(
                        new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8));
                StringBuilder response = new StringBuilder();
                String line;
                while ((line = br.readLine()) != null) {
                    response.append(line);
                }
                br.close();
                return response.toString();
            } else {
                System.err.println("[Telemetry] Server returned: " + responseCode);
            }
        } catch (Exception e) {
            System.err.println("[Telemetry] Send failed: " + e.getMessage());
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
        return null;
    }

    /**
     * Get the current session ID (for debugging).
     */
    public static int getSessionId() {
        return sessionId;
    }

    /**
     * Get the current player ID (for debugging).
     */
    public static int getPlayerId() {
        return playerId;
    }

    /**
     * Check if telemetry is active.
     */
    public static boolean isActive() {
        return initialized;
    }
}
