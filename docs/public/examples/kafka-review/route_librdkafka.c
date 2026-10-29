/* Independent teaching example. Requires librdkafka v2.8.0 development files.
 * Sends one record to an isolated test topic. No cluster execution claimed.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <librdkafka/rdkafka.h>

static int delivered = 0;
static int failed = 0;

static void delivery(rd_kafka_t *rk, const rd_kafka_message_t *m, void *opaque) {
    (void)rk; (void)opaque;
    delivered++;
    if (m->err) {
        failed = 1;
        fprintf(stderr, "delivery failed: %s\n", rd_kafka_message_errstr(m));
    } else {
        printf("delivered topic=%s partition=%" PRId32 " offset=%" PRId64 "\n",
               rd_kafka_topic_name(m->rkt), m->partition, m->offset);
    }
}

static void setconf(rd_kafka_conf_t *conf, const char *key, const char *value) {
    char error[512];
    if (rd_kafka_conf_set(conf, key, value, error, sizeof(error)) != RD_KAFKA_CONF_OK) {
        fprintf(stderr, "%s: %s\n", key, error);
        exit(1);
    }
}

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "bootstrap topic consistent_random|murmur2_random\n"); return 1; }
    if (rd_kafka_version() != 0x020800ff) {
        fprintf(stderr, "Expected v2.8.0, got %s\n", rd_kafka_version_str()); return 1;
    }
    if (strcmp(argv[3], "consistent_random") && strcmp(argv[3], "murmur2_random")) return 1;
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    setconf(conf, "bootstrap.servers", argv[1]);
    setconf(conf, "partitioner", argv[3]);
    setconf(conf, "acks", "all");
    setconf(conf, "enable.idempotence", "true");
    setconf(conf, "message.timeout.ms", "30000");
    rd_kafka_conf_set_dr_msg_cb(conf, delivery);
    char error[512];
    rd_kafka_t *rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf, error, sizeof(error));
    if (!rk) { fprintf(stderr, "%s\n", error); rd_kafka_conf_destroy(conf); return 1; }
    rd_kafka_topic_t *topic = rd_kafka_topic_new(rk, argv[2], NULL);
    if (!topic) { fprintf(stderr, "topic handle failed\n"); rd_kafka_destroy(rk); return 1; }
    const struct rd_kafka_metadata *metadata = NULL;
    rd_kafka_resp_err_t err = rd_kafka_metadata(rk, 0, topic, &metadata, 10000);
    int partitions = -1;
    if (!err) {
        for (int i = 0; i < metadata->topic_cnt; ++i)
            if (!strcmp(metadata->topics[i].topic, argv[2]) && !metadata->topics[i].err)
                partitions = metadata->topics[i].partition_cnt;
        rd_kafka_metadata_destroy(metadata);
    }
    if (err || partitions != 4) {
        fprintf(stderr, "metadata error=%s partitions=%d (expected 4)\n", rd_kafka_err2str(err), partitions);
        rd_kafka_topic_destroy(topic); rd_kafka_destroy(rk); return 1;
    }
    const char key[] = "order-42";
    char value[] = "c-routing-example";
    printf("client=%s partitioner=%s key.len=%zu key.hex=", rd_kafka_version_str(), argv[3], strlen(key));
    for (size_t i = 0; i < strlen(key); ++i) printf("%02x", (unsigned char)key[i]);
    printf(" partitions=%d\n", partitions);
    err = rd_kafka_producev(rk, RD_KAFKA_V_RKT(topic), RD_KAFKA_V_PARTITION(RD_KAFKA_PARTITION_UA),
        RD_KAFKA_V_MSGFLAGS(RD_KAFKA_MSG_F_COPY), RD_KAFKA_V_KEY(key, strlen(key)),
        RD_KAFKA_V_VALUE(value, strlen(value)), RD_KAFKA_V_END);
    if (err) fprintf(stderr, "enqueue failed: %s\n", rd_kafka_err2str(err));
    rd_kafka_resp_err_t flush_error = rd_kafka_flush(rk, 35000);
    int ok = !err && !flush_error && delivered == 1 && !failed;
    if (flush_error) {
        fprintf(stderr, "flush failed: %s (delivery may be unknown)\n", rd_kafka_err2str(flush_error));
        rd_kafka_purge(rk, RD_KAFKA_PURGE_F_QUEUE | RD_KAFKA_PURGE_F_INFLIGHT);
        rd_kafka_poll(rk, 0);
    }
    rd_kafka_topic_destroy(topic);
    rd_kafka_destroy(rk);
    return ok ? 0 : 1;
}
