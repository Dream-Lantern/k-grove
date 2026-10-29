// Independent teaching example. Requires Kafka Java Client 3.9.0 and JDK.
// Sends one record to an isolated test topic; not run against a cluster here.
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Properties;
import java.util.concurrent.TimeUnit;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.apache.kafka.common.serialization.ByteArraySerializer;
import org.apache.kafka.common.utils.AppInfoParser;

public final class RouteJava {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("bootstrap topic");
        String version = AppInfoParser.getVersion();
        if (!"3.9.0".equals(version)) throw new IllegalStateException("Expected 3.9.0, got " + version);
        byte[] key = "order-42".getBytes(StandardCharsets.UTF_8);
        Properties p = new Properties();
        p.put("bootstrap.servers", args[0]);
        p.put("key.serializer", ByteArraySerializer.class.getName());
        p.put("value.serializer", ByteArraySerializer.class.getName());
        p.put("partitioner.ignore.keys", "false");
        p.put("acks", "all");
        p.put("enable.idempotence", "true");
        p.put("delivery.timeout.ms", "30000");
        p.put("request.timeout.ms", "10000");
        p.put("max.block.ms", "10000");
        KafkaProducer<byte[], byte[]> producer = new KafkaProducer<>(p);
        try {
            int count = producer.partitionsFor(args[1]).size();
            if (count != 4) throw new IllegalStateException("Expected 4 partitions, got " + count);
            StringBuilder hex = new StringBuilder();
            for (byte b : key) hex.append(String.format("%02x", b & 0xff));
            System.out.printf("client=%s partitioner=built-in ignore.keys=false key.len=%d key.hex=%s partitions=%d%n",
                              version, key.length, hex, count);
            RecordMetadata result = producer.send(new ProducerRecord<>(args[1], key,
                "java-routing-example".getBytes(StandardCharsets.UTF_8))).get(35, TimeUnit.SECONDS);
            System.out.printf("delivered topic=%s partition=%d offset=%d%n",
                              result.topic(), result.partition(), result.offset());
        } finally {
            producer.close(Duration.ofSeconds(5));
        }
    }
}
