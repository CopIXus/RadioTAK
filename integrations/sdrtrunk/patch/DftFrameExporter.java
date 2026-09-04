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
import io.github.dsheirer.controller.channel.ChannelModel;
import io.github.dsheirer.properties.SystemProperties;
import io.github.dsheirer.spectrum.DFTResultsListener;
import io.github.dsheirer.spectrum.OverlayPanel;
import java.util.LinkedHashSet;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Streams downsampled DFT bins as NDJSON to RadioTAK (default 127.0.0.1:29501).
 *
 * Isolated from decoder/audio paths. Enable with spectrum_export_enabled in
 * SDRTrunk.properties.
 */
public class DftFrameExporter implements DFTResultsListener
{
    private static final Logger mLog = LoggerFactory.getLogger(DftFrameExporter.class);
    public static final String ENABLED = "spectrum_export_enabled";
    public static final String HOST = "spectrum_export_host";
    public static final String PORT = "spectrum_export_port";
    private static final int TARGET_BINS = 512;
    private static final long MIN_INTERVAL_MS = 120;

    private final OverlayPanel mOverlayPanel;
    private final ChannelModel mChannelModel;
    private final NdjsonTcpClient mClient;
    private final boolean mEnabled;
    private long mLastFrameAt;

    public DftFrameExporter(OverlayPanel overlayPanel, ChannelModel channelModel)
    {
        mOverlayPanel = overlayPanel;
        mChannelModel = channelModel;
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
        long fMin = 0;
        long fMax = 0;
        try
        {
            fMin = mOverlayPanel.getMinFrequency();
            fMax = mOverlayPanel.getMaxFrequency();
        }
        catch(Exception ignored)
        {
        }

        StringBuilder sb = new StringBuilder(bins.length * 8 + 128);
        sb.append("{\"schema\":\"sdr2tak.spectrum.v1\",\"bins\":[");
        for(int i = 0; i < bins.length; i++)
        {
            if(i > 0)
            {
                sb.append(',');
            }
            sb.append(String.format(Locale.US, "%.5f", bins[i]));
        }
        sb.append("],\"f_min\":").append(fMin);
        sb.append(",\"f_max\":").append(fMax);
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
}
