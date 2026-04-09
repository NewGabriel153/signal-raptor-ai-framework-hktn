from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


engine = create_async_engine(
	settings.async_database_url,
	echo=settings.ECHO_SQL,
)

AsyncSessionFactory = async_sessionmaker(
	bind=engine,
	autoflush=False,
	expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
	async with AsyncSessionFactory() as session:
		try:
			yield session
		except Exception:
			await session.rollback()
			raise