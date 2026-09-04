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

import io.github.dsheirer.channel.IChannelDescriptor;
import io.github.dsheirer.identifier.Identifier;
import io.github.dsheirer.identifier.IdentifierCollection;
import io.github.dsheirer.module.decode.event.DecodeEventType;
import io.github.dsheirer.module.decode.event.IDecodeEvent;
import io.github.dsheirer.module.decode.event.PlottableDecodeEvent;
import io.github.dsheirer.properties.SystemProperties;
import io.github.dsheirer.protocol.Protocol;
import io.github.dsheirer.sample.Listener;
import java.time.Instant;
import java.util.Locale;
import java.util.UUID;
import org.jdesktop.swingx.mapviewer.GeoPosition;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Streams PlottableDecodeEvent GPS as NDJSON to RadioTAK (default 127.0.0.1:29500).
 *
 * Isolated from decoder/audio paths. Enable with geo_event_export_enabled in
 * SDRTrunk.properties.
 */
public class GeoEventJsonExporter implements Listener<IDecodeEvent>
{
    private static final Logger mLog = LoggerFactory.getLogger(GeoEventJsonExporter.class);
    public static final String ENABLED = "geo_event_export_enabled";
    public static final String HOST = "geo_event_export_host";
    public static final String PORT = "geo_event_export_port";

    private final NdjsonTcpClient mClient;
    private final boolean mEnabled;

    public GeoEventJsonExporter()
    {
        SystemProperties props = SystemProperties.getInstance();
        mEnabled = props.get(ENABLED, true);
        String host = props.get(HOST, "127.0.0.1");
        int port = props.get(PORT, 29500);
        if(mEnabled)
        {
            mClient = new NdjsonTcpClient("geo", host, port);
            mClient.start();
        }
        else
        {
            mClient = null;
            mLog.info("geo event export disabled");
        }
    }

    @Override
    public void receive(IDecodeEvent decodeEvent)
    {
        if(!mEnabled || !(decodeEvent instanceof PlottableDecodeEvent plottable))
        {
            return;
        }
        if(!plottable.isValidLocation())
        {
            return;
        }
        GeoPosition pos = plottable.getLocation();
        IdentifierCollection ids = plottable.getIdentifierCollection();
        Identifier from = ids != null ? ids.getFromIdentifier() : null;
        if(from == null || from.getValue() == null)
        {
            return;
        }
        String radioId = String.valueOf(from.getValue());
        if(radioId.isBlank())
        {
            return;
        }

        StringBuilder sb = new StringBuilder(256);
        sb.append("{\"schema\":\"sdr2tak.location.v1\"");
        sb.append(",\"event_id\":\"").append(UUID.randomUUID()).append('"');
        sb.append(",\"decoder\":\"sdrtrunk\"");
        field(sb, "protocol", protocol(plottable));
        field(sb, "system_name", aliasListName(ids));
        field(sb, "radio_id", radioId);
        Identifier to = ids != null ? ids.getToIdentifier() : null;
        if(to != null && to.getValue() != null)
        {
            field(sb, "talkgroup", String.valueOf(to.getValue()));
        }
        sb.append(",\"latitude\":").append(String.format(Locale.US, "%.7f", pos.getLatitude()));
        sb.append(",\"longitude\":").append(String.format(Locale.US, "%.7f", pos.getLongitude()));
        double heading = plottable.getHeading();
        if(!Double.isNaN(heading) && heading >= 0 && heading < 360)
        {
            sb.append(",\"heading_deg\":").append(String.format(Locale.US, "%.1f", heading));
        }
        double kph = plottable.getSpeed();
        if(!Double.isNaN(kph) && kph > 0)
        {
            sb.append(",\"speed_mps\":").append(String.format(Locale.US, "%.3f", kph / 3.6));
        }
        IChannelDescriptor channel = plottable.getChannelDescriptor();
        if(channel != null && channel.getDownlinkFrequency() > 0)
        {
            sb.append(",\"frequency_hz\":").append(channel.getDownlinkFrequency());
        }
        sb.append(",\"emergency\":").append(plottable.getEventType() == DecodeEventType.EMERGENCY);
        field(sb, "raw_event_type", plottable.getEventType() != null ? plottable.getEventType().name() : null);
        sb.append(",\"observed_at\":\"").append(Instant.ofEpochMilli(plottable.getTimeStart())).append('"');
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

    private static String protocol(PlottableDecodeEvent event)
    {
        Protocol p = event.getProtocol();
        return p == null ? null : p.name();
    }

    private static String aliasListName(IdentifierCollection ids)
    {
        if(ids == null || !ids.hasAliasListConfiguration())
        {
            return null;
        }
        Identifier alias = ids.getAliasListConfiguration();
        return alias == null || alias.getValue() == null ? null : String.valueOf(alias.getValue());
    }

    private static void field(StringBuilder sb, String name, String value)
    {
        if(value == null || value.isBlank())
        {
            return;
        }
        sb.append(",\"").append(name).append("\":\"").append(escape(value)).append('"');
    }

    private static String escape(String value)
    {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
