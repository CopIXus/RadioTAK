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

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Background NDJSON TCP client. Drops the oldest queued line when the RadioTAK
 * listener is slow so decoder/FFT threads never block.
 *
 * RadioTAK never sends anything back, so a dedicated reader thread blocks on the
 * socket input and treats EOF as "peer went away" — otherwise a client that only
 * writes on sparse events (GPS) would sit on a half-closed socket for hours after a
 * RadioTAK restart. An empty-line heartbeat while idle gives the kernel a chance to
 * surface a reset as well; RadioTAK's NDJSON parsers skip blank lines.
 */
public class NdjsonTcpClient
{
    private static final Logger mLog = LoggerFactory.getLogger(NdjsonTcpClient.class);
    private static final int QUEUE_SIZE = 8;
    private static final int CONNECT_TIMEOUT_MS = 1500;
    private static final long HEARTBEAT_MS = 5_000;

    private final String mHost;
    private final int mPort;
    private final String mName;
    private final ArrayBlockingQueue<String> mQueue = new ArrayBlockingQueue<>(QUEUE_SIZE);
    private final AtomicBoolean mRunning = new AtomicBoolean();
    private final AtomicBoolean mPeerClosed = new AtomicBoolean();
    private Thread mThread;
    private volatile Socket mSocket;
    private OutputStream mOutput;
    private long mLastWriteAt;

    public NdjsonTcpClient(String name, String host, int port)
    {
        mName = name;
        mHost = host;
        mPort = port;
    }

    public synchronized void start()
    {
        if(mRunning.compareAndSet(false, true))
        {
            mThread = new Thread(this::runLoop, "radiotak-" + mName + "-export");
            mThread.setDaemon(true);
            mThread.start();
            mLog.info("{} exporter connecting to {}:{}", mName, mHost, mPort);
        }
    }

    public void send(String line)
    {
        if(!mRunning.get() || line == null || line.isEmpty())
        {
            return;
        }
        if(!mQueue.offer(line))
        {
            mQueue.poll();
            mQueue.offer(line);
        }
    }

    public synchronized void stop()
    {
        mRunning.set(false);
        if(mThread != null)
        {
            mThread.interrupt();
        }
        closeQuietly();
    }

    private void runLoop()
    {
        long backoffMs = 500;
        while(mRunning.get())
        {
            try
            {
                ensureConnected();
                String line = mQueue.poll(500, TimeUnit.MILLISECONDS);
                if(line == null)
                {
                    if(System.currentTimeMillis() - mLastWriteAt >= HEARTBEAT_MS)
                    {
                        write("");
                    }
                    continue;
                }
                write(line);
                backoffMs = 500;
            }
            catch(InterruptedException ie)
            {
                Thread.currentThread().interrupt();
                return;
            }
            catch(Exception e)
            {
                closeQuietly();
                try
                {
                    Thread.sleep(backoffMs);
                }
                catch(InterruptedException ie)
                {
                    Thread.currentThread().interrupt();
                    return;
                }
                backoffMs = Math.min(backoffMs * 2, 15_000);
            }
        }
        closeQuietly();
    }

    private void write(String line) throws IOException
    {
        mOutput.write((line + "\n").getBytes(StandardCharsets.UTF_8));
        mOutput.flush();
        mLastWriteAt = System.currentTimeMillis();
    }

    private void ensureConnected() throws IOException
    {
        if(mSocket != null && mSocket.isConnected() && !mSocket.isClosed() && !mPeerClosed.get())
        {
            return;
        }
        if(mPeerClosed.get())
        {
            mLog.info("{} exporter: RadioTAK closed the connection — reconnecting", mName);
        }
        closeQuietly();
        Socket socket = new Socket();
        socket.connect(new InetSocketAddress(mHost, mPort), CONNECT_TIMEOUT_MS);
        socket.setTcpNoDelay(true);
        socket.setKeepAlive(true);
        mSocket = socket;
        mOutput = socket.getOutputStream();
        mPeerClosed.set(false);
        mLastWriteAt = System.currentTimeMillis();
        startPeerWatch(socket);
        mLog.info("{} exporter connected to {}:{}", mName, mHost, mPort);
    }

    /**
     * Blocks on the socket input; RadioTAK never writes, so any return means the peer closed.
     */
    private void startPeerWatch(final Socket socket)
    {
        Thread watcher = new Thread(() ->
        {
            try
            {
                InputStream in = socket.getInputStream();
                byte[] scratch = new byte[64];
                while(!socket.isClosed())
                {
                    if(in.read(scratch) < 0)
                    {
                        break;
                    }
                }
            }
            catch(IOException ignored)
            {
            }
            finally
            {
                if(socket == mSocket)
                {
                    mPeerClosed.set(true);
                }
            }
        }, "radiotak-" + mName + "-export-watch");
        watcher.setDaemon(true);
        watcher.start();
    }

    private void closeQuietly()
    {
        mPeerClosed.set(false);
        if(mOutput != null)
        {
            try
            {
                mOutput.close();
            }
            catch(IOException ignored)
            {
            }
            mOutput = null;
        }
        if(mSocket != null)
        {
            try
            {
                mSocket.close();
            }
            catch(IOException ignored)
            {
            }
            mSocket = null;
        }
    }
}
