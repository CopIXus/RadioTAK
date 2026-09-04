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
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.jdesktop.swingx.mapviewer.GeoPosition;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Streams PlottableDecodeEvent GPS and encrypted/clear call metadata as NDJSON
 * to RadioTAK (default 127.0.0.1:29500).
 *
 * Isolated from decoder/audio paths. Enable with geo_event_export_enabled in
 * SDRTrunk.properties. Call events are rate-limited per radio/talkgroup.
 */
public class GeoEventJsonExporter implements Listener<IDecodeEvent>
{
    private static final Logger mLog = LoggerFactory.getLogger(GeoEventJsonExporter.class);
    public static final String ENABLED = "geo_event_export_enabled";
    public static final String HOST = "geo_event_export_host";
    public static final String PORT = "geo_event_export_port";
    private static final long DECODE_MIN_INTERVAL_MS = 2500L;
    private static final Pattern ALG_KEY = Pattern.compile(
        "(?:ALGORITHM|ALGID)\\s*[:=]\\s*(?:0x)?([0-9A-Fa-f]+).*?(?:KEY(?:\\s*ID)?)\\s*[:=]\\s*(?:0x)?([0-9A-Fa-f]+)",
        Pattern.CASE_INSENSITIVE | Pattern.DOTALL);

    private final NdjsonTcpClient mClient;
    private final boolean mEnabled;
    private final TrafficKeyStore mKeys;
    private final Map<String, Long> mLastDecode = new ConcurrentHashMap<>();

    public GeoEventJsonExporter()
    {
        SystemProperties props = SystemProperties.getInstance();
        mEnabled = props.get(ENABLED, true);
        String host = props.get(HOST, "127.0.0.1");
        int port = props.get(PORT, 29500);
        mKeys = new TrafficKeyStore(props.get(TrafficKeyStore.PATH_PROPERTY, ""));
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
        if(!mEnabled || decodeEvent == null)
        {
            return;
        }
        if(decodeEvent instanceof PlottableDecodeEvent plottable && plottable.isValidLocation())
        {
            emitLocation(plottable);
            return;
        }
        DecodeEventType type = decodeEvent.getEventType();
        if(!isCallLike(type))
        {
            return;
        }
        emitDecode(decodeEvent);
    }

    public void dispose()
    {
        if(mClient != null)
        {
            mClient.stop();
        }
    }

    private void emitLocation(PlottableDecodeEvent plottable)
    {
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

    private void emitDecode(IDecodeEvent event)
    {
        IdentifierCollection ids = event.getIdentifierCollection();
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
        Identifier to = ids != null ? ids.getToIdentifier() : null;
        String talkgroup = to != null && to.getValue() != null ? String.valueOf(to.getValue()) : "";
        DecodeEventType type = event.getEventType();
        boolean encrypted = isEncrypted(type, event.getDetails());
        String dedupe = radioId + "|" + talkgroup + "|" + encrypted;
        long now = System.currentTimeMillis();
        Long last = mLastDecode.get(dedupe);
        if(last != null && now - last < DECODE_MIN_INTERVAL_MS)
        {
            return;
        }
        mLastDecode.put(dedupe, now);

        Integer algId = encryptionAlgorithm(event.getDetails());
        Integer keyId = encryptionKeyId(event.getDetails());
        boolean keyLoaded = mKeys.hasKey(algId, keyId);

        StringBuilder sb = new StringBuilder(256);
        sb.append("{\"schema\":\"sdr2tak.decode.v1\"");
        sb.append(",\"event_id\":\"").append(UUID.randomUUID()).append('"');
        sb.append(",\"decoder\":\"sdrtrunk\"");
        field(sb, "protocol", protocol(event));
        field(sb, "system_name", aliasListName(ids));
        field(sb, "radio_id", radioId);
        if(!talkgroup.isBlank())
        {
            field(sb, "talkgroup", talkgroup);
        }
        sb.append(",\"encrypted\":").append(encrypted);
        sb.append(",\"key_loaded\":").append(keyLoaded);
        if(algId != null)
        {
            sb.append(",\"algorithm_id\":").append(algId);
            field(sb, "algorithm_id_hex", String.format(Locale.US, "%02X", algId));
        }
        if(keyId != null)
        {
            sb.append(",\"key_id\":").append(keyId);
        }
        IChannelDescriptor channel = event.getChannelDescriptor();
        if(channel != null && channel.getDownlinkFrequency() > 0)
        {
            sb.append(",\"frequency_hz\":").append(channel.getDownlinkFrequency());
        }
        sb.append(",\"emergency\":").append(type == DecodeEventType.EMERGENCY);
        field(sb, "raw_event_type", type != null ? type.name() : null);
        field(sb, "details", event.getDetails());
        sb.append(",\"observed_at\":\"").append(Instant.ofEpochMilli(event.getTimeStart())).append('"');
        sb.append('}');
        mClient.send(sb.toString());
    }

    private static boolean isCallLike(DecodeEventType type)
    {
        if(type == null)
        {
            return false;
        }
        String name = type.name();
        return name.startsWith("CALL") || name.startsWith("DATA_CALL");
    }

    private static boolean isEncrypted(DecodeEventType type, String details)
    {
        if(type != null && type.name().contains("ENCRYPTED"))
        {
            return true;
        }
        if(details == null)
        {
            return false;
        }
        String upper = details.toUpperCase(Locale.ROOT);
        return upper.contains("ENCRYPTED") && !upper.contains("UNENCRYPTED");
    }

    private static Integer encryptionAlgorithm(String details)
    {
        Matcher matcher = ALG_KEY.matcher(details == null ? "" : details);
        if(matcher.find())
        {
            return TrafficKeyStore.parseHexInt(matcher.group(1));
        }
        return null;
    }

    private static Integer encryptionKeyId(String details)
    {
        Matcher matcher = ALG_KEY.matcher(details == null ? "" : details);
        if(matcher.find())
        {
            return TrafficKeyStore.parseHexInt(matcher.group(2));
        }
        return null;
    }

    private static String protocol(IDecodeEvent event)
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
