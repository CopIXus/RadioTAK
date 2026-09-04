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

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reads RadioTAK traffic_keys.json so encrypted-call exports can flag a matching
 * ALGID+KID. Does not load key material and does not decrypt audio.
 */
public class TrafficKeyStore
{
    private static final Logger mLog = LoggerFactory.getLogger(TrafficKeyStore.class);
    public static final String PATH_PROPERTY = "traffic_keys_path";

    private final Set<String> mIndex = new HashSet<>();

    public TrafficKeyStore(String path)
    {
        if(path == null || path.isBlank())
        {
            return;
        }
        Path file = Path.of(path.trim());
        if(!Files.isRegularFile(file))
        {
            mLog.info("traffic keys file not present: {}", file);
            return;
        }
        try
        {
            ObjectMapper mapper = new ObjectMapper();
            JsonNode root = mapper.readTree(file.toFile());
            JsonNode keys = root.path("keys");
            if(!keys.isArray())
            {
                return;
            }
            for(JsonNode key : keys)
            {
                Integer alg = intField(key, "algorithm_id");
                Integer kid = intField(key, "key_id");
                if(alg == null)
                {
                    alg = parseHexInt(textField(key, "algorithm_id_hex"));
                }
                if(alg == null || kid == null)
                {
                    continue;
                }
                mIndex.add(indexKey(alg, kid));
            }
            mLog.info("loaded {} traffic key id(s) from {}", mIndex.size(), file);
        }
        catch(Exception e)
        {
            mLog.warn("failed reading traffic keys from {}: {}", file, e.getMessage());
        }
    }

    public boolean hasKey(Integer algorithmId, Integer keyId)
    {
        if(algorithmId == null || keyId == null)
        {
            return false;
        }
        return mIndex.contains(indexKey(algorithmId, keyId));
    }

    public boolean isEmpty()
    {
        return mIndex.isEmpty();
    }

    private static String indexKey(int algorithmId, int keyId)
    {
        return algorithmId + ":" + keyId;
    }

    private static Integer intField(JsonNode node, String name)
    {
        JsonNode value = node.get(name);
        if(value == null || value.isNull() || value.isMissingNode())
        {
            return null;
        }
        if(value.isInt() || value.isLong())
        {
            return value.asInt();
        }
        return parseHexInt(value.asText());
    }

    private static String textField(JsonNode node, String name)
    {
        JsonNode value = node.get(name);
        if(value == null || value.isNull() || !value.isTextual())
        {
            return null;
        }
        return value.asText();
    }

    static Integer parseHexInt(String raw)
    {
        if(raw == null)
        {
            return null;
        }
        String text = raw.trim().toLowerCase(Locale.ROOT);
        if(text.isEmpty())
        {
            return null;
        }
        if(text.startsWith("0x"))
        {
            text = text.substring(2);
        }
        try
        {
            if(text.chars().allMatch(ch -> Character.digit(ch, 16) >= 0) && text.length() <= 4)
            {
                return Integer.parseUnsignedInt(text, 16);
            }
            return Integer.parseInt(text);
        }
        catch(NumberFormatException e)
        {
            return null;
        }
    }
}
