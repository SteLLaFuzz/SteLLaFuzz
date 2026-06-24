#!/bin/bash

if [ -z $KEY ]; then
    echo "NO OPENAI API KEY PROVIDED! Please set the KEY environment variable"
    exit 0
fi

# Update the openAI key
for x in ChatAFL;
do
  sed -i "s/#define OPENAI_TOKEN \".*\"/#define OPENAI_TOKEN \"$KEY\"/" $x/chat-llm.h
done

for y in DICOM/Dcmtk DNS/Dnsmasq DTLS/TinyDTLS SSH/OpenSSH TLS/OpenSSL;
do
  sed -i "s/ENV OPENAI_API_KEY=\".*\"/ENV OPENAI_API_KEY=\"$KEY\"/" benchmark/subjects/$y/Dockerfile
done

for y in DAAP/forked-daapd FTP/BFTPD FTP/LightFTP FTP/ProFTPD FTP/PureFTPD HTTP/Lighttpd1 RTSP/Live555 SIP/Kamailio SMTP/Exim;
do
  sed -i "s/ENV OPENAI_API_KEY=\".*\"/ENV OPENAI_API_KEY=\"$KEY\"/" benchmark/subjects/$y/Dockerfile
done

# Copy the different versions of ChatAFL to the benchmark directories
for subject in ./benchmark/subjects/*/*; do
  rm -r $subject/aflnet 2>&1 >/dev/null
  cp -r aflnet $subject/aflnet

  rm -r $subject/chatafl 2>&1 >/dev/null
  cp -r ChatAFL $subject/chatafl
  
  rm -r $subject/stellafuzz 2>&1 >/dev/null
  cp -r SteLLaFuzz $subject/stellafuzz
done;

# Build the docker images

PFBENCH="$PWD/benchmark"
cd $PFBENCH
PFBENCH=$PFBENCH scripts/execution/profuzzbench_build_all.sh
