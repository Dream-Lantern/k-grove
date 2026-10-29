// Independent teaching sender. Kafka Java Client 3.9.0, JDK, isolated topic.
// Not a throughput benchmark; prints final callbacks, not just enqueue results.
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.common.utils.AppInfoParser;

public final class BatchJava {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("bootstrap topic none|lz4|zstd");
        if (!"3.9.0".equals(AppInfoParser.getVersion())) throw new IllegalStateException("Expected client 3.9.0");
        if (!Arrays.asList("none", "lz4", "zstd").contains(args[2])) throw new IllegalArgumentException("codec");
        Properties p = new Properties();
        p.put("bootstrap.servers", args[0]);
        p.put("key.serializer", ByteArraySerializer.class.getName());
        p.put("value.serializer", ByteArraySerializer.class.getName());
        p.put("acks", "all");
        p.put("enable.idempotence", "true");
        p.put("batch.size", "16384");
        p.put("linger.ms", "5");
        p.put("compression.type", args[2]);
        p.put("delivery.timeout.ms", "15000");
        p.put("request.timeout.ms", "5000");
        p.put("max.block.ms", "10000");
        AtomicInteger succeeded = new AtomicInteger();
        AtomicInteger failed = new AtomicInteger();
        List<Future<RecordMetadata>> futures = new ArrayList<>();
        KafkaProducer<byte[], byte[]> producer = new KafkaProducer<>(p);
        try {
            for (int i = 0; i < 20; i++) {
                final String eventId = String.format("event-%05d", i);
                byte[] value = new byte[500];
                Arrays.fill(value, (byte)'x');
                byte[] prefix = eventId.getBytes(StandardCharsets.UTF_8);
                System.arraycopy(prefix, 0, value, 0, prefix.length);
                futures.add(producer.send(new ProducerRecord<>(args[1],
                    "order-42".getBytes(StandardCharsets.UTF_8), value), (metadata, error) -> {
                    if (error != null) {
                        failed.incrementAndGet();
                        System.err.printf("%s delivery failed: %s%n", eventId, error);
                    } else {
                        succeeded.incrementAndGet();
                        System.out.printf("%s delivered partition=%d offset=%d%n", eventId,
                                          metadata.partition(), metadata.offset());
                    }
                }));
            }
            producer.flush();
            for (Future<RecordMetadata> future : futures) future.get(35, TimeUnit.SECONDS);
            System.out.printf("callbacks ok=%d failed=%d%n", succeeded.get(), failed.get());
            if (succeeded.get() != 20 || failed.get() != 0) throw new IllegalStateException("Incomplete delivery");
        } finally {
            producer.close(Duration.ofSeconds(5));
        }
    }
}
