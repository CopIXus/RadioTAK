/*
 * *****************************************************************************
 * Copyright (C) 2014-2026 Dennis Sheirer
 * Copyright (C) 2026 CopIXus / RadioTAK
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>
 * ****************************************************************************
 */
package io.github.dsheirer.export;

import io.github.dsheirer.audio.AudioSegment;
import io.github.dsheirer.identifier.Form;
import io.github.dsheirer.identifier.Identifier;
import io.github.dsheirer.identifier.IdentifierCollection;
import io.github.dsheirer.properties.SystemProperties;
import io.github.dsheirer.sample.Listener;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.LinkedTransferQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Streams decoded talkgroup PCM (and encrypted-call silence markers) as NDJSON
 * to RadioTAK (default 127.0.0.1:29502).
 *
 * Consumer of {@link AudioSegment} only — does not change vocoder, mixer, or
 * playback. Encrypted segments never include PCM. Enable with
 * audio_export_enabled in SDRTrunk.properties.
 *
 * Register next to AudioPlaybackManager:
 * {@code channelProcessingManager.addAudioSegmentListener(new AudioFrameExporter());}
 */
public class AudioFrameExporter implements Listener<AudioSegment>
{
    private static final Logger mLog = LoggerFactory.getLogger(AudioFrameExporter.class);
    public static final String ENABLED = "audio_export_enabled";
    public static final String HOST = "audio_export_host";
    public static final String PORT = "audio_export_port";
    private static final int SAMPLE_RATE = 8000;
    private static final int BATCH_SAMPLES = 800; // 100 ms at 8 kHz
    private static final long SILENCE_INTERVAL_MS = 1000;
    private static final int QUEUE_SIZE = 64;

    private final NdjsonTcpClient mClient;
    private final boolean mEnabled;
    private final LinkedTransferQueue<AudioSegment> mIncoming = new LinkedTransferQueue<>();
    private final List<Tracked> mTracked = new ArrayList<>();
    private final AtomicBoolean mRunning = new AtomicBoolean();
    private Thread mThread;

    public AudioFrameExporter()
    {
        SystemProperties props = SystemProperties.getInstance();
        mEnabled = props.get(ENABLED, true);
        String host = props.get(HOST, "127.0.0.1");
        int port = props.get(PORT, 29502);
        if(mEnabled)
        {
            mClient = new NdjsonTcpClient("audio", host, port, QUEUE_SIZE);
            mClient.start();
            mRunning.set(true);
            mThread = new Thread(this::runLoop, "radiotak-audio-export");
            mThread.setDaemon(true);
            mThread.start();
            mLog.info("audio export enabled → {}:{}", host, port);
        }
        else
        {
            mClient = null;
            mLog.info("audio export disabled");
        }
    }

    @Override
    public void receive(AudioSegment audioSegment)
    {
        if(audioSegment == null)
        {
            return;
        }
        if(!mEnabled)
        {
            audioSegment.decrementConsumerCount();
            return;
        }
        mIncoming.add(audioSegment);
    }

    public void dispose()
    {
        mRunning.set(false);
        if(mThread != null)
        {
            mThread.interrupt();
        }
        for(Tracked tracked : mTracked)
        {
            tracked.segment.decrementConsumerCount();
        }
        mTracked.clear();
        AudioSegment leftover = mIncoming.poll();
        while(leftover != null)
        {
            leftover.decrementConsumerCount();
            leftover = mIncoming.poll();
        }
        if(mClient != null)
        {
            mClient.stop();
        }
    }

    private void runLoop()
    {
        while(mRunning.get())
        {
            try
            {
                AudioSegment incoming = mIncoming.poll(50, TimeUnit.MILLISECONDS);
                while(incoming != null)
                {
                    if(incoming.isDuplicate())
                    {
                        incoming.decrementConsumerCount();
                    }
                    else
                    {
                        mTracked.add(new Tracked(incoming));
                    }
                    incoming = mIncoming.poll();
                }
                pump();
            }
            catch(InterruptedException ie)
            {
                Thread.currentThread().interrupt();
                return;
            }
            catch(Exception e)
            {
                mLog.debug("audio export pump error: {}", e.toString());
            }
        }
    }

    private void pump()
    {
        long now = System.currentTimeMillis();
        Iterator<Tracked> it = mTracked.iterator();
        while(it.hasNext())
        {
            Tracked tracked = it.next();
            AudioSegment segment = tracked.segment;
            try
            {
                if(segment.isEncrypted())
                {
                    tracked.pending.reset();
                    if(now - tracked.lastSilenceAt >= SILENCE_INTERVAL_MS)
                    {
                        emit(segment, null, true, false);
                        tracked.lastSilenceAt = now;
                    }
                }
                else
                {
                    drainNewBuffers(tracked);
                    if(tracked.pending.size() >= BATCH_SAMPLES * 2)
                    {
                        emit(segment, tracked.takePending(), false, false);
                    }
                }

                if(segment.isComplete())
                {
                    if(!segment.isEncrypted() && tracked.pending.size() > 0)
                    {
                        emit(segment, tracked.takePending(), false, false);
                    }
                    emit(segment, null, segment.isEncrypted(), true);
                    segment.decrementConsumerCount();
                    it.remove();
                }
            }
            catch(Exception e)
            {
                mLog.debug("audio export segment error: {}", e.toString());
                try
                {
                    segment.decrementConsumerCount();
                }
                catch(Exception ignored)
                {
                }
                it.remove();
            }
        }
    }

    private static void drainNewBuffers(Tracked tracked)
    {
        int count = tracked.segment.getAudioBufferCount();
        while(tracked.nextBuffer < count)
        {
            float[] samples = tracked.segment.getAudioBuffer(tracked.nextBuffer);
            tracked.nextBuffer++;
            if(samples == null || samples.length == 0)
            {
                continue;
            }
            appendPcm(tracked.pending, samples);
        }
    }

    static void appendPcm(ByteArrayOutputStream pending, float[] samples)
    {
        for(float sample : samples)
        {
            float clipped = sample;
            if(clipped > 1f)
            {
                clipped = 1f;
            }
            else if(clipped < -1f)
            {
                clipped = -1f;
            }
            int s = Math.round(clipped * 32767f);
            pending.write(s & 0xFF);
            pending.write((s >> 8) & 0xFF);
        }
    }

    private void emit(AudioSegment segment, byte[] pcm, boolean encrypted, boolean end)
    {
        if(mClient == null)
        {
            return;
        }
        IdentifierCollection ids = segment.getIdentifierCollection();
        Identifier from = ids != null ? ids.getFromIdentifier() : null;
        Identifier to = ids != null ? ids.getToIdentifier() : null;
        String radioId = from != null && from.getValue() != null ? String.valueOf(from.getValue()) : "";
        String talkgroup = "";
        if(to != null && to.getValue() != null && to.getForm() != Form.RADIO)
        {
            talkgroup = String.valueOf(to.getValue());
        }
        StringBuilder sb = new StringBuilder(pcm != null ? pcm.length * 2 + 192 : 192);
        sb.append("{\"schema\":\"sdr2tak.audio.v1\"");
        sb.append(",\"encrypted\":").append(encrypted);
        sb.append(",\"silence\":").append(encrypted || pcm == null || pcm.length == 0);
        sb.append(",\"end\":").append(end);
        sb.append(",\"sample_rate\":").append(SAMPLE_RATE);
        sb.append(",\"channels\":1");
        sb.append(",\"encoding\":\"pcm_s16le\"");
        sb.append(",\"timeslot\":").append(segment.getTimeslot());
        field(sb, "talkgroup", talkgroup);
        field(sb, "radio_id", radioId);
        if(pcm != null && pcm.length > 0 && !encrypted)
        {
            sb.append(",\"pcm_b64\":\"").append(Base64.getEncoder().encodeToString(pcm)).append('"');
        }
        sb.append(",\"ts\":").append(System.currentTimeMillis() / 1000.0);
        sb.append('}');
        mClient.send(sb.toString());
    }

    private static void field(StringBuilder sb, String name, String value)
    {
        if(value == null || value.isBlank())
        {
            return;
        }
        sb.append(",\"").append(name).append("\":\"");
        sb.append(value.replace("\\", "\\\\").replace("\"", "\\\""));
        sb.append('"');
    }

    private static final class Tracked
    {
        final AudioSegment segment;
        final ByteArrayOutputStream pending = new ByteArrayOutputStream(1600);
        int nextBuffer;
        long lastSilenceAt;

        Tracked(AudioSegment segment)
        {
            this.segment = segment;
        }

        byte[] takePending()
        {
            byte[] pcm = pending.toByteArray();
            pending.reset();
            return pcm;
        }
    }
}
