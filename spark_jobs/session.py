"""Shared SparkSession for all Spark jobs."""

from pyspark.sql import SparkSession

SPARK_CONFIG = {
    # local mode: the driver is also the only executor, so this is the memory for all the work
    "spark.driver.memory": "4g",
    # shuffles (join, groupBy) produce 200 partitions by default, too many small tasks for this data
    "spark.sql.shuffle.partitions": "20",
}


def get_spark(app_name: str) -> SparkSession:
    """A local SparkSession on all cores. The config has to be set before
    getOrCreate(), because that is when the JVM starts."""
    spark = (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        .config(map=SPARK_CONFIG)
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark
