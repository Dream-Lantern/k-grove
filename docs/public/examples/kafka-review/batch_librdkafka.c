/* Independent teaching sender; requires librdkafka v2.8.0 development library.
 * Runs only when explicitly invoked against an isolated test topic.
 * Not a benchmark. event IDs are synthetic and repeat on a new program run.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <librdkafka/rdkafka.h>

static int ok_count = 0, failed_count = 0;
static void delivery(rd_kafka_t *rk, const rd_kafka_message_t *m, void *opaque) {
    (void)rk; (void)opaque;
    rd_kafka_msg_status_t state = rd_kafka_message_status(m);
    if (m->err) {
        failed_count++;
        fprintf(stderr, "event=%.11s delivery failed error=%s status=%d\n",
                m->payload ? (const char *)m->payload : "<unknown>", rd_kafka_message_errstr(m), (int)state);
    } else {
        ok_count++;
        printf("event=%.11s delivered partition=%" PRId32 " offset=%" PRId64 " status=%d\n",
               m->payload ? (const char *)m->payload : "<unknown>", m->partition, m->offset, (int)state);
    }
}
static void setconf(rd_kafka_conf_t *conf, const char *key, const char *value) {
    char error[512];
    if (rd_kafka_conf_set(conf, key, value, error, sizeof(error)) != RD_KAFKA_CONF_OK) {
        fprintf(stderr, "%s: %s\n", key, error); exit(1);
    }
}
int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "bootstrap topic none|lz4|zstd\n"); return 1; }
    if (rd_kafka_version() != 0x020800ff) { fprintf(stderr, "Expected v2.8.0\n"); return 1; }
    if (strcmp(argv[3], "none") && strcmp(argv[3], "lz4") && strcmp(argv[3], "zstd")) return 1;
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    setconf(conf, "bootstrap.servers", argv[1]);
    setconf(conf, "acks", "all");
    setconf(conf, "enable.idempotence", "true");
    setconf(conf, "batch.size", "1000000");
    setconf(conf, "batch.num.messages", "10000");
    setconf(conf, "linger.ms", "5");
    setconf(conf, "compression.codec", argv[3]);
    setconf(conf, "message.timeout.ms", "15000");
    setconf(conf, "request.timeout.ms", "5000");
    rd_kafka_conf_set_dr_msg_cb(conf, delivery);
    char error[512];
    rd_kafka_t *rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf, error, sizeof(error));
    if (!rk) { fprintf(stderr, "%s\n", error); rd_kafka_conf_destroy(conf); return 1; }
    int accepted = 0, enqueue_failed = 0;
    for (int i = 0; i < 20; i++) {
        char value[500];
        memset(value, 'x', sizeof(value));
        char event_id[32];
        snprintf(event_id, sizeof(event_id), "event-%05d", i);
        memcpy(value, event_id, strlen(event_id));
        rd_kafka_resp_err_t err = RD_KAFKA_RESP_ERR_NO_ERROR;
        for (int attempt = 0; attempt < 100; attempt++) {
            err = rd_kafka_producev(rk, RD_KAFKA_V_TOPIC(argv[2]),
                RD_KAFKA_V_MSGFLAGS(RD_KAFKA_MSG_F_COPY),
                RD_KAFKA_V_KEY("order-42", 8), RD_KAFKA_V_VALUE(value, sizeof(value)), RD_KAFKA_V_END);
            if (err != RD_KAFKA_RESP_ERR__QUEUE_FULL) break;
            rd_kafka_poll(rk, 100);
        }
        if (err) { fprintf(stderr, "%s enqueue failed: %s\n", event_id, rd_kafka_err2str(err)); enqueue_failed++; }
        else accepted++;
        rd_kafka_poll(rk, 0);
    }
    rd_kafka_resp_err_t flushed = rd_kafka_flush(rk, 20000);
    int success = !flushed && !enqueue_failed && accepted == 20 && ok_count == 20 && !failed_count;
    if (flushed) {
        fprintf(stderr, "flush incomplete error=%s remaining=%d; in-flight delivery may be unknown\n",
                rd_kafka_err2str(flushed), rd_kafka_outq_len(rk));
        rd_kafka_purge(rk, RD_KAFKA_PURGE_F_QUEUE | RD_KAFKA_PURGE_F_INFLIGHT);
        rd_kafka_poll(rk, 0);
    }
    printf("accepted=%d delivered=%d delivery-failed=%d enqueue-failed=%d\n",
           accepted, ok_count, failed_count, enqueue_failed);
    rd_kafka_destroy(rk);
    return success ? 0 : 1;
}
