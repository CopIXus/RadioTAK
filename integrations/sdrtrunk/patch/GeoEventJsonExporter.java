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
 * along with this program.  If not, see <https://www.gnu.org/licenses/>
 * ****************************************************************************
 */
package io.github.dsheirer.export;

import io.github.dsheirer.channel.IChannelDescriptor;
import io.github.dsheirer.identifier.Form;
import io.github.dsheirer.identifier.Identifier;
import io.github.dsheirer.identifier.IdentifierCollection;
import io.github.dsheirer.identifier.encryption.EncryptionKey;
import io.github.dsheirer.identifier.encryption.EncryptionKeyIdentifier;
import io.github.dsheirer.module.decode.event.DecodeEventType;
import io.github.dsheirer.module.decode.event.IDecodeEvent;
import io.github.dsheirer.module.decode.event.PlottableDecodeEvent;
import io.github.dsheirer.properties.SystemProperties;
import io.github.dsheirer.protocol.Protocol;
import io.github.dsheirer.sample.Listener;
import java.time.Instant;
import java.util.List;
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
 *
 * Extra P25 context (system/site/NAC/WACN/RFSS, timeslot, uplink, patch/status/LRA,
 * structured ALGID/KID, Message Indicator when the decoder already printed it)
 * is copied from IdentifierCollection. This exporter does not decrypt payloads.
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
    private static final Pattern MESSAGE_INDICATOR = Pattern.compile(
        "(?:\\bMI\\b|MESSAGE\\s*INDICATOR)\\s*[:=]\\s*(?:0x)?([0-9A-Fa-f]{6,})",
        Pattern.CASE_INSENSITIVE);

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

        StringBuilder sb = new StringBuilder(384);
        sb.append("{\"schema\":\"sdr2tak.location.v1\"");
        sb.append(",\"event_id\":\"").append(UUID.randomUUID()).append('"');
        sb.append(",\"decoder\":\"sdrtrunk\"");
        field(sb, "protocol", protocol(plottable));
        field(sb, "p25_phase", p25Phase(plottable.getProtocol()));
        field(sb, "system_name", aliasListName(ids));
        appendSystemContext(sb, ids, plottable.getChannelDescriptor());
        field(sb, "radio_id", radioId);
        field(sb, "source_alias", identifierValue(ids, Form.TALKER_ALIAS));
        Identifier to = ids != null ? ids.getToIdentifier() : null;
        if(to != null && to.getValue() != null)
        {
            if(to.getForm() == Form.RADIO)
            {
                field(sb, "destination_radio_id", String.valueOf(to.getValue()));
            }
            else
            {
                field(sb, "talkgroup", String.valueOf(to.getValue()));
            }
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
        String talkgroup = "";
        String destinationRadio = null;
        String destinationType = null;
        if(to != null && to.getValue() != null)
        {
            destinationType = to.getForm() != null ? to.getForm().name() : null;
            if(to.getForm() == Form.RADIO)
            {
                destinationRadio = String.valueOf(to.getValue());
            }
            else
            {
                talkgroup = String.valueOf(to.getValue());
            }
        }
        DecodeEventType type = event.getEventType();
        boolean encryptionHeaderPresent = false;
        Integer[] cipher = encryptionFromIdentifiers(ids);
        if(cipher != null)
        {
            encryptionHeaderPresent = true;
        }
        else
        {
            cipher = encryptionFromDetails(event.getDetails());
        }
        Integer algId = cipher != null ? cipher[0] : null;
        Integer keyId = cipher != null ? cipher[1] : null;
        boolean encrypted = isEncrypted(type, event.getDetails()) || algId != null;
        String dedupe = radioId + "|" + talkgroup + "|" + encrypted + "|" +
            (algId != null ? algId : "") + "|" + (keyId != null ? keyId : "");
        long now = System.currentTimeMillis();
        Long last = mLastDecode.get(dedupe);
        if(last != null && now - last < DECODE_MIN_INTERVAL_MS)
        {
            return;
        }
        mLastDecode.put(dedupe, now);

        boolean keyLoaded = mKeys.hasKey(algId, keyId);
        String mi = messageIndicator(event.getDetails());

        StringBuilder sb = new StringBuilder(512);
        sb.append("{\"schema\":\"sdr2tak.decode.v1\"");
        sb.append(",\"event_id\":\"").append(UUID.randomUUID()).append('"');
        sb.append(",\"decoder\":\"sdrtrunk\"");
        field(sb, "protocol", protocol(event));
        field(sb, "p25_phase", p25Phase(event.getProtocol()));
        field(sb, "system_name", aliasListName(ids));
        appendSystemContext(sb, ids, event.getChannelDescriptor());
        field(sb, "radio_id", radioId);
        field(sb, "source_type", from.getForm() != null ? from.getForm().name() : null);
        field(sb, "source_alias", identifierValue(ids, Form.TALKER_ALIAS));
        if(!talkgroup.isBlank())
        {
            field(sb, "talkgroup", talkgroup);
        }
        field(sb, "destination_type", destinationType);
        if(destinationRadio != null)
        {
            field(sb, "destination_radio_id", destinationRadio);
        }
        appendEntityContext(sb, ids);
        sb.append(",\"encrypted\":").append(encrypted);
        sb.append(",\"encryption_header_present\":").append(encryptionHeaderPresent);
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
        if(mi != null)
        {
            field(sb, "message_indicator", mi);
            field(sb, "message_indicator_hex", mi);
        }
        long duration = event.getDuration();
        if(duration > 0)
        {
            sb.append(",\"duration_ms\":").append(duration);
        }
        sb.append(",\"emergency\":").append(type == DecodeEventType.EMERGENCY);
        field(sb, "raw_event_type", type != null ? type.name() : null);
        field(sb, "details", event.getDetails());
        sb.append(",\"observed_at\":\"").append(Instant.ofEpochMilli(event.getTimeStart())).append('"');
        sb.append('}');
        mClient.send(sb.toString());
    }

    private static void appendSystemContext(StringBuilder sb, IdentifierCollection ids,
                                            IChannelDescriptor channel)
    {
        field(sb, "system_id", identifierValue(ids, Form.SYSTEM));
        field(sb, "wacn", identifierValue(ids, Form.WACN));
        field(sb, "nac", identifierValue(ids, Form.NETWORK_ACCESS_CODE));
        field(sb, "site_id", identifierValue(ids, Form.SITE));
        field(sb, "rfss", identifierValue(ids, Form.RF_SUBSYSTEM));
        if(ids != null)
        {
            int slot = ids.getTimeslot();
            if(channel != null && channel.isTDMAChannel())
            {
                sb.append(",\"timeslot\":").append(slot);
            }
            else if(slot > 0)
            {
                sb.append(",\"timeslot\":").append(slot);
            }
        }
        if(channel != null)
        {
            if(channel.getDownlinkFrequency() > 0)
            {
                sb.append(",\"frequency_hz\":").append(channel.getDownlinkFrequency());
            }
            if(channel.getUplinkFrequency() > 0)
            {
                sb.append(",\"uplink_frequency_hz\":").append(channel.getUplinkFrequency());
            }
            String channelName = channel.toString();
            if(channelName != null && !channelName.isBlank())
            {
                field(sb, "channel", channelName);
            }
        }
        else
        {
            field(sb, "channel", identifierValue(ids, Form.CHANNEL_NAME));
            String channelFreq = identifierValue(ids, Form.CHANNEL_FREQUENCY);
            if(channelFreq != null)
            {
                try
                {
                    sb.append(",\"frequency_hz\":").append(Long.parseLong(channelFreq));
                }
                catch(NumberFormatException ignored)
                {
                    field(sb, "channel", channelFreq);
                }
            }
        }
    }

    private static void appendEntityContext(StringBuilder sb, IdentifierCollection ids)
    {
        field(sb, "patch_group", identifierValue(ids, Form.PATCH_GROUP));
        field(sb, "unit_status", identifierValue(ids, Form.UNIT_STATUS));
        field(sb, "user_status", identifierValue(ids, Form.USER_STATUS));
        field(sb, "lra", identifierValue(ids, Form.LOCATION_REGISTRATION_AREA));
    }

    private static Integer[] encryptionFromIdentifiers(IdentifierCollection ids)
    {
        if(ids == null)
        {
            return null;
        }
        Identifier identifier = ids.getEncryptionIdentifier();
        if(identifier == null)
        {
            List<Identifier> list = ids.getIdentifiers(Form.ENCRYPTION_KEY);
            if(list == null || list.isEmpty())
            {
                return null;
            }
            identifier = list.get(0);
        }
        Object value = identifier.getValue();
        if(identifier instanceof EncryptionKeyIdentifier keyIdentifier)
        {
            value = keyIdentifier.getValue();
        }
        if(!(value instanceof EncryptionKey key) || !key.isEncrypted())
        {
            return null;
        }
        return new Integer[]{key.getAlgorithm(), key.getKey()};
    }

    private static Integer[] encryptionFromDetails(String details)
    {
        Matcher matcher = ALG_KEY.matcher(details == null ? "" : details);
        if(!matcher.find())
        {
            return null;
        }
        return new Integer[]{
            TrafficKeyStore.parseHexInt(matcher.group(1)),
            TrafficKeyStore.parseHexInt(matcher.group(2))
        };
    }

    private static String messageIndicator(String details)
    {
        if(details == null || details.isBlank())
        {
            return null;
        }
        Matcher matcher = MESSAGE_INDICATOR.matcher(details);
        if(!matcher.find())
        {
            return null;
        }
        return matcher.group(1).toUpperCase(Locale.ROOT);
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

    private static String protocol(IDecodeEvent event)
    {
        Protocol p = event.getProtocol();
        return p == null ? null : p.name();
    }

    private static String p25Phase(Protocol protocol)
    {
        if(protocol == null)
        {
            return null;
        }
        String name = protocol.name().toUpperCase(Locale.ROOT);
        if(name.contains("PHASE2") || name.contains("P2") || name.contains("TDMA"))
        {
            return "2";
        }
        if(name.contains("APCO25") || name.contains("P25") || name.contains("PHASE1"))
        {
            return "1";
        }
        return null;
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

    private static String identifierValue(IdentifierCollection ids, Form form)
    {
        if(ids == null || form == null)
        {
            return null;
        }
        List<Identifier> list = ids.getIdentifiers(form);
        if(list == null || list.isEmpty())
        {
            return null;
        }
        Identifier identifier = list.get(0);
        if(identifier == null || identifier.getValue() == null)
        {
            return null;
        }
        Object value = identifier.getValue();
        if(value instanceof Number number)
        {
            int numeric = number.intValue();
            if(form == Form.SYSTEM || form == Form.WACN || form == Form.NETWORK_ACCESS_CODE)
            {
                return Integer.toHexString(numeric).toUpperCase(Locale.ROOT);
            }
            return String.valueOf(numeric);
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
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
