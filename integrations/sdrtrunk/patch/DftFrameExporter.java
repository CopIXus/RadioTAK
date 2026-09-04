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

import io.github.dsheirer.controller.channel.Channel;
import io.github.dsheirer.controller.channel.ChannelEvent;
import io.github.dsheirer.controller.channel.ChannelModel;
import io.github.dsheirer.properties.SystemProperties;
import io.github.dsheirer.sample.Listener;
import io.github.dsheirer.source.ISourceEventProcessor;
import io.github.dsheirer.source.SourceEvent;
import io.github.dsheirer.source.SourceException;
import io.github.dsheirer.source.tuner.Tuner;
import io.github.dsheirer.spectrum.DFTResultsListener;
import io.github.dsheirer.spectrum.OverlayPanel;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Streams downsampled DFT bins as NDJSON to RadioTAK (default 127.0.0.1:29501).
 *
 * Isolated from decoder/audio paths. Enable with spectrum_export_enabled in
 * SDRTrunk.properties.
 *
 * Frequency labels prefer the live tuner LO (the stick producing these DFT
 * bins), then OverlayPanel, then the first processing playlist channel when
 * showFirstTuner() left the spectral panel parked on an idle frequency.
 */
public class DftFrameExporter implements DFTResultsListener, Listener<ChannelEvent>, ISourceEventProcessor
{
    private static final Logger mLog = LoggerFactory.getLogger(DftFrameExporter.class);
    public static final String ENABLED = "spectrum_export_enabled";
    public static final String HOST = "spectrum_export_host";
    public static final String PORT = "spectrum_export_port";
    private static final int TARGET_BINS = 512;
    private static final long MIN_INTERVAL_MS = 120;

    private final OverlayPanel mOverlayPanel;
    private final ChannelModel mChannelModel;
    private final Supplier<Tuner> mTunerSupplier;
    private final NdjsonTcpClient mClient;
    private final boolean mEnabled;
    private long mLastFrameAt;
    private Tuner mBoundTuner;
    private volatile long mTunerCenterHz;
    private volatile int mTunerBandwidthHz;
    private boolean mLoggedPanelMismatch;

    public DftFrameExporter(OverlayPanel overlayPanel, ChannelModel channelModel)
    {
        this(overlayPanel, channelModel, null);
    }

    /**
     * @param tunerSupplier SpectralDisplayPanel::getTuner so labels follow the
     *        stick actually feeding ComplexDecibelConverter, not a stale overlay.
     */
    public DftFrameExporter(OverlayPanel overlayPanel, ChannelModel channelModel, Supplier<Tuner> tunerSupplier)
    {
        mOverlayPanel = overlayPanel;
        mChannelModel = channelModel;
        mTunerSupplier = tunerSupplier;
        SystemProperties props = SystemProperties.getInstance();
        mEnabled = props.get(ENABLED, true);
        String host = props.get(HOST, "127.0.0.1");
        int port = props.get(PORT, 29501);
        if(mEnabled)
        {
            mClient = new NdjsonTcpClient("spectrum", host, port);
            mClient.start();
        }
        else
        {
            mClient = null;
            mLog.info("spectrum export disabled");
        }
        if(mChannelModel != null)
        {
            mChannelModel.addListener(this);
        }
    }

    /**
     * Bind to the tuner currently shown in the spectral display so frequency
     * change events update labels even when OverlayPanel misses them.
     */
    public void bindTuner(Tuner tuner)
    {
        if(mBoundTuner != null)
        {
            try
            {
                mBoundTuner.getTunerController().removeListener(this);
            }
            catch(Exception ignored)
            {
            }
        }
        mBoundTuner = tuner;
        mTunerCenterHz = 0;
        mTunerBandwidthHz = 0;
        if(tuner != null)
        {
            try
            {
                tuner.getTunerController().addListener(this);
                captureTunerSpan(tuner);
            }
            catch(Exception ignored)
            {
            }
        }
    }

    @Override
    public void process(SourceEvent event) throws SourceException
    {
        if(event == null)
        {
            return;
        }
        switch(event.getEvent())
        {
            case NOTIFICATION_FREQUENCY_CHANGE:
                if(event.getValue() != null)
                {
                    mTunerCenterHz = event.getValue().longValue();
                }
                break;
            case NOTIFICATION_SAMPLE_RATE_CHANGE:
                if(event.getValue() != null)
                {
                    mTunerBandwidthHz = event.getValue().intValue();
                }
                break;
            default:
                break;
        }
    }

    @Override
    public void receive(ChannelEvent event)
    {
        if(event == null || event.getEvent() != ChannelEvent.Event.NOTIFICATION_PROCESSING_START)
        {
            return;
        }
        Channel channel = event.getChannel();
        if(channel == null || !channel.isStandardChannel())
        {
            return;
        }
        Tuner tuner = currentTuner();
        if(tuner != null)
        {
            captureTunerSpan(tuner);
        }
    }

    @Override
    public void receive(float[] results)
    {
        if(!mEnabled || results == null || results.length == 0)
        {
            return;
        }
        long now = System.currentTimeMillis();
        if(now - mLastFrameAt < MIN_INTERVAL_MS)
        {
            return;
        }
        mLastFrameAt = now;

        double[] bins = downsampleLinear(results, TARGET_BINS);
        Span span = frequencySpan();

        StringBuilder sb = new StringBuilder(bins.length * 8 + 160);
        sb.append("{\"schema\":\"sdr2tak.spectrum.v1\",\"bins\":[");
        for(int i = 0; i < bins.length; i++)
        {
            if(i > 0)
            {
                sb.append(',');
            }
            sb.append(String.format(Locale.US, "%.5f", bins[i]));
        }
        sb.append("],\"f_min\":").append(span.fMin);
        sb.append(",\"f_max\":").append(span.fMax);
        if(span.panelMin != span.fMin || span.panelMax != span.fMax)
        {
            sb.append(",\"panel_f_min\":").append(span.panelMin);
            sb.append(",\"panel_f_max\":").append(span.panelMax);
        }
        sb.append(",\"cc_hz\":[");
        boolean first = true;
        for(long hz : controlChannels())
        {
            if(!first)
            {
                sb.append(',');
            }
            sb.append(hz);
            first = false;
        }
        sb.append("],\"ts\":").append(now / 1000.0);
        sb.append('}');
        mClient.send(sb.toString());
    }

    public void dispose()
    {
        bindTuner(null);
        if(mChannelModel != null)
        {
            try
            {
                mChannelModel.removeListener(this);
            }
            catch(Exception ignored)
            {
            }
        }
        if(mClient != null)
        {
            mClient.stop();
        }
    }

    /**
     * Convert dB bins to linear power and average-downsample to target length.
     * RadioTAK's canvas max-normalizes each row, so linear values keep peaks
     * brighter than the noise floor.
     */
    static double[] downsampleLinear(float[] dbBins, int target)
    {
        int n = dbBins.length;
        int outLen = Math.min(target, n);
        double[] out = new double[outLen];
        if(n <= outLen)
        {
            for(int i = 0; i < n; i++)
            {
                out[i] = linear(dbBins[i]);
            }
            return out;
        }
        double step = (double)n / outLen;
        for(int i = 0; i < outLen; i++)
        {
            int start = (int)(i * step);
            int end = (int)((i + 1) * step);
            if(end <= start)
            {
                end = start + 1;
            }
            if(end > n)
            {
                end = n;
            }
            double sum = 0;
            int count = 0;
            for(int j = start; j < end; j++)
            {
                sum += linear(dbBins[j]);
                count++;
            }
            out[i] = count == 0 ? 0 : sum / count;
        }
        return out;
    }

    private static double linear(float db)
    {
        if(Float.isNaN(db) || db < -180f)
        {
            return 0;
        }
        return Math.pow(10.0, db / 10.0);
    }

    private Span frequencySpan()
    {
        long panelMin = 0;
        long panelMax = 0;
        try
        {
            if(mOverlayPanel != null)
            {
                panelMin = mOverlayPanel.getMinFrequency();
                panelMax = mOverlayPanel.getMaxFrequency();
            }
        }
        catch(Exception ignored)
        {
        }

        Tuner tuner = currentTuner();
        if(tuner != null)
        {
            captureTunerSpan(tuner);
        }
        if(mTunerCenterHz > 0 && mTunerBandwidthHz > 0)
        {
            long half = mTunerBandwidthHz / 2L;
            return new Span(mTunerCenterHz - half, mTunerCenterHz + half, panelMin, panelMax);
        }

        Channel processing = firstProcessingStandard();
        if(processing != null && !processing.isWithin(panelMin, panelMax))
        {
            long bw = panelMax > panelMin ? panelMax - panelMin : 0;
            long[] labeled = spanForChannel(processing, bw);
            if(labeled != null)
            {
                if(!mLoggedPanelMismatch)
                {
                    mLoggedPanelMismatch = true;
                    mLog.info("spectrum axis using listening channel {}-{} Hz (spectral panel was {}-{} Hz)",
                        labeled[0], labeled[1], panelMin, panelMax);
                }
                return new Span(labeled[0], labeled[1], panelMin, panelMax);
            }
        }
        return new Span(panelMin, panelMax, panelMin, panelMax);
    }

    private Tuner currentTuner()
    {
        if(mBoundTuner != null)
        {
            return mBoundTuner;
        }
        if(mTunerSupplier == null)
        {
            return null;
        }
        try
        {
            return mTunerSupplier.get();
        }
        catch(Exception ignored)
        {
            return null;
        }
    }

    private void captureTunerSpan(Tuner tuner)
    {
        if(tuner == null || tuner.getTunerController() == null)
        {
            return;
        }
        try
        {
            long center = tuner.getTunerController().getFrequency();
            int bw = tuner.getTunerController().getBandwidth();
            if(bw <= 0)
            {
                bw = (int)tuner.getTunerController().getSampleRate();
            }
            if(center > 0)
            {
                mTunerCenterHz = center;
            }
            if(bw > 0)
            {
                mTunerBandwidthHz = bw;
            }
        }
        catch(Exception ignored)
        {
        }
    }

    private Channel firstProcessingStandard()
    {
        if(mChannelModel == null)
        {
            return null;
        }
        try
        {
            for(Channel channel : mChannelModel.getChannels())
            {
                if(channel != null && channel.isStandardChannel() && channel.isProcessing())
                {
                    return channel;
                }
            }
        }
        catch(Exception ignored)
        {
        }
        return null;
    }

    /**
     * Place the overlay bandwidth around the listening channel so RadioTAK's
     * cyan CC markers land on the canvas. When all CCs fit in the tuner
     * bandwidth, center on their midpoint; otherwise follow the first CC.
     */
    static long[] spanForChannel(Channel channel, long bandwidthHz)
    {
        if(channel == null || bandwidthHz <= 0)
        {
            return null;
        }
        List<?> freqs;
        try
        {
            freqs = channel.getFrequencyList();
        }
        catch(Exception ignored)
        {
            return null;
        }
        if(freqs == null || freqs.isEmpty())
        {
            return null;
        }
        long min = Long.MAX_VALUE;
        long max = Long.MIN_VALUE;
        long first = 0;
        for(Object raw : freqs)
        {
            long hz = toHz(raw);
            if(hz <= 0)
            {
                continue;
            }
            if(first == 0)
            {
                first = hz;
            }
            if(hz < min)
            {
                min = hz;
            }
            if(hz > max)
            {
                max = hz;
            }
        }
        if(first <= 0)
        {
            return null;
        }
        long center = (max - min) <= bandwidthHz ? (min + max) / 2L : first;
        long half = bandwidthHz / 2L;
        return new long[]{center - half, center + half};
    }

    private static long toHz(Object raw)
    {
        if(raw instanceof Number number)
        {
            return number.longValue();
        }
        return 0;
    }

    private LinkedHashSet<Long> controlChannels()
    {
        LinkedHashSet<Long> hz = new LinkedHashSet<>();
        if(mChannelModel == null)
        {
            return hz;
        }
        try
        {
            for(Channel channel : mChannelModel.getChannels())
            {
                if(channel == null)
                {
                    continue;
                }
                for(Long f : channel.getFrequencyList())
                {
                    if(f != null && f > 0)
                    {
                        hz.add(f);
                    }
                }
            }
        }
        catch(Exception ignored)
        {
        }
        return hz;
    }

    private static final class Span
    {
        final long fMin;
        final long fMax;
        final long panelMin;
        final long panelMax;

        Span(long fMin, long fMax, long panelMin, long panelMax)
        {
            this.fMin = fMin;
            this.fMax = fMax;
            this.panelMin = panelMin;
            this.panelMax = panelMax;
        }
    }
}
