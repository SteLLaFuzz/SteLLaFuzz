#!/bin/bash

export NUM_CONTAINERS="${NUM_CONTAINERS:-10}"
export TIMEOUT="${TIMEOUT:-86400}"
export SKIPCOUNT="${SKIPCOUNT:-1}"
export TEST_TIMEOUT="${TEST_TIMEOUT:-20000}"

export TARGET_LIST=$1
export FUZZER_LIST=$2

if [[ "x$TARGET_LIST" == "x" ]] || [[ "x$FUZZER_LIST" == "x" ]]
then
    echo "Usage: $0 TARGET FUZZER"
    exit 1
fi

echo
echo "# NUM_CONTAINERS: ${NUM_CONTAINERS}"
echo "# TIMEOUT: ${TIMEOUT} s"
echo "# SKIPCOUNT: ${SKIPCOUNT}"
echo "# TEST TIMEOUT: ${TEST_TIMEOUT} ms"
echo "# TARGET LIST: ${TARGET_LIST}"
echo "# FUZZER LIST: ${FUZZER_LIST}"
echo

for FUZZER in $(echo $FUZZER_LIST | sed "s/,/ /g")
do

    for TARGET in $(echo $TARGET_LIST | sed "s/,/ /g")
    do

        echo
        echo "***** RUNNING $FUZZER ON $TARGET *****"
        echo

##### FTP #####

        if [[ $TARGET == "lightftp" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-lightftp

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh lightftp $NUM_CONTAINERS results-lightftp aflnet out-lightftp-aflnet "-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh lightftp $NUM_CONTAINERS results-lightftp chatafl out-lightftp-chatafl "-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh lightftp $NUM_CONTAINERS results-lightftp stellafuzz out-lightftp-stellafuzz "-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi


        if [[ $TARGET == "bftpd" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-bftpd

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh bftpd $NUM_CONTAINERS results-bftpd aflnet out-bftpd-aflnet "-m none -P FTP -D 10000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh bftpd $NUM_CONTAINERS results-bftpd chatafl out-bftpd-chatafl "-m none -P FTP -D 10000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh bftpd $NUM_CONTAINERS results-bftpd stellafuzz out-bftpd-stellafuzz "-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi


        if [[ $TARGET == "proftpd" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-proftpd

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh proftpd $NUM_CONTAINERS results-proftpd aflnet out-proftpd-aflnet "-m none -P FTP -D 10000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh proftpd $NUM_CONTAINERS results-proftpd chatafl out-proftpd-chatafl "-m none -P FTP -D 10000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh proftpd $NUM_CONTAINERS results-proftpd stellafuzz out-proftpd-stellafuzz "-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

        if [[ $TARGET == "pure-ftpd" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-pure-ftpd

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh pure-ftpd $NUM_CONTAINERS results-pure-ftpd aflnet out-pure-ftpd-aflnet "-m none -P FTP -D 10000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh pure-ftpd $NUM_CONTAINERS results-pure-ftpd chatafl out-pure-ftpd-chatafl "-m none -P FTP -D 10000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh pure-ftpd $NUM_CONTAINERS results-pure-ftpd stellafuzz out-pure-ftpd-stellafuzz "-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi


##### SMTP #####

        if [[ $TARGET == "exim" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-exim

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh exim $NUM_CONTAINERS results-exim aflnet out-exim-aflnet "-P SMTP -D 10000 -q 3 -s 3 -E -K -W 100 -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh exim $NUM_CONTAINERS results-exim chatafl out-exim-chatafl "-P SMTP -D 10000 -q 3 -s 3 -E -K -W 100 -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh exim $NUM_CONTAINERS results-exim stellafuzz out-exim-stellafuzz "-P SMTP -D 10000 -q 3 -s 3 -E -K -W 100 -m none -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi


##### RTSP #####

        if [[ $TARGET == "live555" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-live555

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh live555 $NUM_CONTAINERS results-live555 aflnet out-live555-aflnet "-P RTSP -D 10000 -q 3 -s 3 -E -K -R -m none" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh live555 $NUM_CONTAINERS results-live555 chatafl out-live555-chatafl "-P RTSP -D 10000 -q 3 -s 3 -E -K -R -m none" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh live555 $NUM_CONTAINERS results-live555 stellafuzz out-live555-stellafuzz "-P RTSP -D 10000 -q 3 -s 3 -E -K -R -m none" $TIMEOUT $SKIPCOUNT &
            fi

        fi


##### SIP #####

        if [[ $TARGET == "kamailio" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-kamailio

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh kamailio $NUM_CONTAINERS results-kamailio aflnet out-kamailio-aflnet "-m none -P SIP -l 5061 -D 50000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi
            
            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh kamailio $NUM_CONTAINERS results-kamailio chatafl out-kamailio-chatafl "-m none -P SIP -l 5061 -D 50000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh kamailio $NUM_CONTAINERS results-kamailio stellafuzz out-kamailio-stellafuzz "-m none -P SIP -l 5061 -D 50000 -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### DAAPD #####

        if [[ $TARGET == "forked-daapd" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-forked-daapd

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh forked-daapd $NUM_CONTAINERS results-forked-daapd aflnet out-forked-daapd-aflnet "-P HTTP -D 200000 -m none -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh forked-daapd $NUM_CONTAINERS results-forked-daapd chatafl out-forked-daapd-chatafl "-P HTTP -D 200000 -m none -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh forked-daapd $NUM_CONTAINERS results-forked-daapd stellafuzz out-forked-daapd-stellafuzz "-P HTTP -D 200000 -m none -q 3 -s 3 -E -K -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### HTTP #####

        if [[ $TARGET == "lighttpd1" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-lighttpd1

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh lighttpd1 $NUM_CONTAINERS results-lighttpd1 aflnet out-lighttpd1-aflnet "-P HTTP -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh lighttpd1 $NUM_CONTAINERS results-lighttpd1 chatafl out-lighttpd1-chatafl "-P HTTP -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh lighttpd1 $NUM_CONTAINERS results-lighttpd1 stellafuzz out-lighttpd1-stellafuzz "-P HTTP -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### DICOM #####

        if [[ $TARGET == "dcmtk" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-dcmtk

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh dcmtk $NUM_CONTAINERS results-dcmtk aflnet out-dcmtk-aflnet "-P DICOM -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh dcmtk $NUM_CONTAINERS results-dcmtk chatafl out-dcmtk-chatafl "-P DICOM -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh dcmtk $NUM_CONTAINERS results-dcmtk stellafuzz out-dcmtk-stellafuzz "-P DICOM -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### DNS #####

        if [[ $TARGET == "dnsmasq" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-dnsmasq

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh dnsmasq $NUM_CONTAINERS results-dnsmasq aflnet out-dnsmasq-aflnet "-P DNS -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh dnsmasq $NUM_CONTAINERS results-dnsmasq chatafl out-dnsmasq-chatafl "-P DNS -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh dnsmasq $NUM_CONTAINERS results-dnsmasq stellafuzz out-dnsmasq-stellafuzz "-P DNS -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### DTLS #####

        if [[ $TARGET == "tinydtls" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-tinydtls

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh tinydtls $NUM_CONTAINERS results-tinydtls aflnet out-tinydtls-aflnet "-P DTLS12 -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh tinydtls $NUM_CONTAINERS results-tinydtls chatafl out-tinydtls-chatafl "-P DTLS12 -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh tinydtls $NUM_CONTAINERS results-tinydtls stellafuzz out-tinydtls-stellafuzz "-P DTLS12 -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### SSH #####

        if [[ $TARGET == "openssh" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-openssh

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh openssh $NUM_CONTAINERS results-openssh aflnet out-openssh-aflnet "-P SSH -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh openssh $NUM_CONTAINERS results-openssh stellafuzz out-openssh-stellafuzz "-P SSH -D 200000 -m none -q 3 -s 3 -E -K -R -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

##### TLS #####

        if [[ $TARGET == "openssl" ]] || [[ $TARGET == "all" ]]
        then

            cd $PFBENCH
            mkdir results-openssl

            if [[ $FUZZER == "aflnet" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh openssl $NUM_CONTAINERS results-openssl aflnet out-openssl-aflnet "-P TLS -D 200000 -m none -q 3 -s 3 -E -K -R -W 100 -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "chatafl" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh openssl $NUM_CONTAINERS results-openssl chatafl out-openssl-chatafl "-P TLS -D 200000 -m none -q 3 -s 3 -E -K -R -W 100 -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

            if [[ $FUZZER == "stellafuzz" ]] || [[ $FUZZER == "all" ]]
            then
                profuzzbench_exec_common.sh openssl $NUM_CONTAINERS results-openssl stellafuzz out-openssl-stellafuzz "-P TLS -D 200000 -m none -q 3 -s 3 -E -K -R -W 100 -t ${TEST_TIMEOUT}+" $TIMEOUT $SKIPCOUNT &
            fi

        fi

        if [[ $TARGET == "all" ]]
        then
            # Quit loop -- all fuzzers and targets have already been executed
            exit
        fi

    done
done

