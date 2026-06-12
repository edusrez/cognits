package storage

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"time"
)

type Session struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	CreatedAt string `json:"createdAt"`
}

type SubagentConfig struct {
	Model     string `json:"model"`
	Reasoning string `json:"reasoning"`
	MaxSteps  int    `json:"maxSteps"`
}

type Config struct {
	LLMProvider  string                     `json:"llmProvider"`
	LLMAgentId   string                     `json:"llmAgentId"`
	LLMApiKey    string                     `json:"llmApiKey"`
	LLMModel     string                     `json:"llmModel"`
	LLMReasoning string                     `json:"llmReasoning"`
	AgentOverrides    map[string]string          `json:"agentOverrides"`
	ChatFontSize      int                        `json:"chatFontSize"`
	TinyfishApiKey    string                     `json:"tinyfishApiKey"`
	TinyfishTier      string                     `json:"tinyfishTier"`
	SubagentConfig    map[string]SubagentConfig  `json:"subagentConfig"`
	UserName                string                     `json:"userName"`
	UserLocation            string                     `json:"userLocation"`
	DefaultLearnitViewport  string                     `json:"defaultLearnitViewport"`
	WriteLangs              []string                   `json:"writeLangs"`
}

// WriteFileAtomic escribe en un temporal y renombra: un crash a mitad de
// escritura no puede dejar el fichero destino truncado o corrupto.
func WriteFileAtomic(path string, data []byte, perm os.FileMode) error {
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, perm); err != nil {
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

type Store struct {
	basePath string
}

func NewStore(basePath string) (*Store, error) {
	if err := os.MkdirAll(basePath, 0755); err != nil {
		return nil, fmt.Errorf("storage: create base dir: %w", err)
	}
	return &Store{basePath: basePath}, nil
}

func (s *Store) BasePath() string {
	return s.basePath
}

func (s *Store) sessionsDir() string {
	return filepath.Join(s.basePath, "sessions")
}

func (s *Store) sessionPath(id string) string {
	return filepath.Join(s.sessionsDir(), id+".json")
}

func (s *Store) InitSessionsDir() error {
	return os.MkdirAll(s.sessionsDir(), 0755)
}

func (s *Store) SaveSession(session Session) error {
	data, err := json.MarshalIndent(session, "", "  ")
	if err != nil {
		return fmt.Errorf("storage: marshal session: %w", err)
	}
	if err := os.WriteFile(s.sessionPath(session.ID), data, 0644); err != nil {
		return fmt.Errorf("storage: write session: %w", err)
	}
	return nil
}

func (s *Store) ListSessions() ([]Session, error) {
	dir := s.sessionsDir()
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return []Session{}, nil
		}
		return nil, fmt.Errorf("storage: read sessions dir: %w", err)
	}

	var sessions = []Session{}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			continue
		}
		var session Session
		if err := json.Unmarshal(data, &session); err != nil {
			continue
		}
		sessions = append(sessions, session)
	}

	sort.Slice(sessions, func(i, j int) bool {
		t1, _ := time.Parse(time.RFC3339, sessions[i].CreatedAt)
		t2, _ := time.Parse(time.RFC3339, sessions[j].CreatedAt)
		return t1.Before(t2)
	})

	return sessions, nil
}

func (s *Store) GetSession(id string) (*Session, error) {
	data, err := os.ReadFile(s.sessionPath(id))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("storage: read session: %w", err)
	}
	var session Session
	if err := json.Unmarshal(data, &session); err != nil {
		return nil, fmt.Errorf("storage: unmarshal session: %w", err)
	}
	return &session, nil
}

func (s *Store) RenameSession(id, newName string) error {
	session, err := s.GetSession(id)
	if err != nil {
		return err
	}
	if session == nil {
		return fmt.Errorf("storage: session %s not found", id)
	}
	session.Name = newName
	return s.SaveSession(*session)
}

func (s *Store) DeleteSession(id string) error {
	err := os.Remove(s.sessionPath(id))
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

func (s *Store) configPath() string {
	return filepath.Join(s.basePath, "config.json")
}

// La clave vive en el directorio de configuración del usuario, no en .learnit/:
// .learnit/ está dentro del proyecto y podría versionarse o sincronizarse junto
// al ciphertext de config.json, anulando el cifrado.
func encryptionKeyPath() (string, error) {
	cfgDir, err := os.UserConfigDir()
	if err != nil {
		return "", fmt.Errorf("storage: user config dir: %w", err)
	}
	return filepath.Join(cfgDir, "learnit", "encryption.key"), nil
}

func (s *Store) legacyEncryptionKeyPath() string {
	return filepath.Join(s.basePath, ".encryption-key")
}

func (s *Store) ensureEncryptionKey() ([]byte, error) {
	keyPath, err := encryptionKeyPath()
	if err != nil {
		return nil, err
	}

	data, err := os.ReadFile(keyPath)
	if err == nil {
		return data, nil
	}
	if !os.IsNotExist(err) {
		return nil, fmt.Errorf("storage: read encryption key: %w", err)
	}

	if err := os.MkdirAll(filepath.Dir(keyPath), 0700); err != nil {
		return nil, fmt.Errorf("storage: create key dir: %w", err)
	}

	// Migración desde la ubicación antigua dentro del proyecto.
	if legacy, err := os.ReadFile(s.legacyEncryptionKeyPath()); err == nil {
		if err := os.WriteFile(keyPath, legacy, 0600); err != nil {
			return nil, fmt.Errorf("storage: migrate encryption key: %w", err)
		}
		_ = os.Remove(s.legacyEncryptionKeyPath())
		return legacy, nil
	}

	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, fmt.Errorf("storage: generate key: %w", err)
	}
	if err := os.WriteFile(keyPath, key, 0600); err != nil {
		return nil, fmt.Errorf("storage: write encryption key: %w", err)
	}
	return key, nil
}

func (s *Store) encryptApiKey(plaintext string) (string, error) {
	if plaintext == "" {
		return "", nil
	}
	key, err := s.ensureEncryptionKey()
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("storage: aes cipher: %w", err)
	}
	aesGCM, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("storage: gcm: %w", err)
	}
	nonce := make([]byte, aesGCM.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", fmt.Errorf("storage: nonce: %w", err)
	}
	ciphertext := aesGCM.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

func (s *Store) decryptApiKey(cipherB64 string) (string, error) {
	if cipherB64 == "" {
		return "", nil
	}
	key, err := s.ensureEncryptionKey()
	if err != nil {
		return "", err
	}
	ciphertext, err := base64.StdEncoding.DecodeString(cipherB64)
	if err != nil {
		return "", fmt.Errorf("storage: decode: %w", err)
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("storage: aes cipher: %w", err)
	}
	aesGCM, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("storage: gcm: %w", err)
	}
	nonceSize := aesGCM.NonceSize()
	if len(ciphertext) < nonceSize {
		return "", fmt.Errorf("storage: ciphertext too short")
	}
	nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := aesGCM.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", fmt.Errorf("storage: decrypt: %w", err)
	}
	return string(plaintext), nil
}

func (s *Store) LoadConfig() (*Config, error) {
	data, err := os.ReadFile(s.configPath())
	if err != nil {
		if os.IsNotExist(err) {
			return &Config{}, nil
		}
		return nil, fmt.Errorf("storage: read config: %w", err)
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("storage: unmarshal config: %w", err)
	}
	if cfg.LLMApiKey != "" {
		decrypted, err := s.decryptApiKey(cfg.LLMApiKey)
		if err != nil {
			return nil, fmt.Errorf("storage: decrypt deepseek api key: %w", err)
		}
		cfg.LLMApiKey = decrypted
	}
	if cfg.TinyfishApiKey != "" {
		decrypted, err := s.decryptApiKey(cfg.TinyfishApiKey)
		if err != nil {
			return nil, fmt.Errorf("storage: decrypt tinyfish api key: %w", err)
		}
		cfg.TinyfishApiKey = decrypted
	}
	return &cfg, nil
}

func (s *Store) SaveConfig(cfg Config) error {
	if err := os.MkdirAll(s.basePath, 0755); err != nil {
		return fmt.Errorf("storage: create config dir: %w", err)
	}
	if cfg.LLMApiKey != "" {
		encrypted, err := s.encryptApiKey(cfg.LLMApiKey)
		if err != nil {
			return fmt.Errorf("storage: encrypt deepseek api key: %w", err)
		}
		cfg.LLMApiKey = encrypted
	}
	if cfg.TinyfishApiKey != "" {
		encrypted, err := s.encryptApiKey(cfg.TinyfishApiKey)
		if err != nil {
			return fmt.Errorf("storage: encrypt tinyfish api key: %w", err)
		}
		cfg.TinyfishApiKey = encrypted
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("storage: marshal config: %w", err)
	}
	if err := WriteFileAtomic(s.configPath(), data, 0644); err != nil {
		return fmt.Errorf("storage: write config: %w", err)
	}
	return nil
}
